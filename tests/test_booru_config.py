import asyncio
import unittest
from unittest.mock import patch

from backend.app.models import BooruConfig, User
from backend.app.routes.booru_config import (BooruConfigCreate,
                                            create_or_update_booru_config,
                                            delete_booru_config)
from backend.app.services.booru import (clear_client_cache,
                                        get_booru_config_for_url,
                                        normalize_domain,
                                        upsert_booru_config)
from backend.app.utils.backup import import_booru_config_logical
from tests.test_base import BlombooruTestSandboxMixin

class TestBooruConfigCaseNormalization(unittest.TestCase, BlombooruTestSandboxMixin):
    def setUp(self):
        self.setup_sandbox()
        clear_client_cache()
        self.user = User(
            id=1,
            username="admin",
            password_hash="testpasshash"
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        clear_client_cache()
        self.teardown_sandbox()

    def test_normalize_domain_helper(self):
        self.assertEqual(normalize_domain("https://Danbooru.Donmai.Us/"), "danbooru.donmai.us")
        self.assertEqual(normalize_domain("https://Danbooru.Donmai.Us/posts/100?q=test#tag"), "danbooru.donmai.us")
        self.assertEqual(normalize_domain("Danbooru.Donmai.Us"), "danbooru.donmai.us")
        self.assertEqual(normalize_domain("http://[::1]:8080/data/test.jpg"), "[::1]:8080")
        self.assertEqual(normalize_domain("[::1]:8080"), "[::1]:8080")
        self.assertEqual(normalize_domain("danbooru.donmai.us:8080/"), "danbooru.donmai.us:8080")
        self.assertEqual(normalize_domain("   https://SAFEBOORU.DONMAI.US/   "), "safebooru.donmai.us")
        self.assertEqual(normalize_domain(""), "")
        self.assertEqual(normalize_domain(None), "")

    def test_create_normalizes_domain_to_lowercase(self):
        req = BooruConfigCreate(
            domain="https://Danbooru.Donmai.Us/",
            username="admin_user",
            api_key="secret123"
        )
        res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
        self.assertEqual(res.domain, "danbooru.donmai.us")

        # Verify stored in DB with normalized lowercase
        db_cfg = self.db.query(BooruConfig).first()
        self.assertIsNotNone(db_cfg)
        self.assertEqual(db_cfg.domain, "danbooru.donmai.us")
        self.assertEqual(db_cfg.username, "admin_user")

    def test_update_matches_existing_mixed_case_and_normalizes_it(self):
        # Insert a pre-existing mixed-case record into DB
        legacy_cfg = BooruConfig(
            domain="Danbooru.Donmai.Us",
            username="old_user",
            api_key="old_key"
        )
        self.db.add(legacy_cfg)
        self.db.commit()

        # Update with lowercase domain
        req = BooruConfigCreate(
            domain="danbooru.donmai.us",
            username="new_user",
            api_key="new_key"
        )
        res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
        self.assertEqual(res.domain, "danbooru.donmai.us")
        self.assertEqual(res.username, "new_user")

        # Ensure no duplicate record exists
        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "danbooru.donmai.us")
        self.assertEqual(all_cfgs[0].username, "new_user")

    def test_update_when_case_duplicates_exist_deduplicates_and_preserves_credentials(self):
        # Insert two records differing only by case:
        # One has mixed case and real credentials, the other is normalized but empty
        cfg_mixed = BooruConfig(
            domain="Safebooru.Donmai.Us",
            username="real_user",
            api_key="secret_key"
        )
        cfg_lower = BooruConfig(
            domain="safebooru.donmai.us",
            username=None,
            api_key=None
        )
        self.db.add_all([cfg_mixed, cfg_lower])
        self.db.commit()

        # Update unrelated field or re-save without providing new api_key
        req = BooruConfigCreate(
            domain="safebooru.donmai.us",
            username="updated_user",
            api_key=None
        )
        with patch("backend.app.services.booru.factory.logger.warning") as mock_warn:
            res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
            mock_warn.assert_called_once()

        self.assertEqual(res.domain, "safebooru.donmai.us")
        self.assertTrue(res.has_api_key)

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "safebooru.donmai.us")
        self.assertEqual(all_cfgs[0].username, "updated_user")
        self.assertEqual(all_cfgs[0].api_key, "secret_key")

    def test_merge_coalesces_split_credentials(self):
        # One duplicate has username, the other has api_key
        cfg1 = BooruConfig(
            domain="Danbooru.Donmai.Us",
            username="split_user",
            api_key=None
        )
        cfg2 = BooruConfig(
            domain="danbooru.donmai.us",
            username=None,
            api_key="split_key"
        )
        self.db.add_all([cfg1, cfg2])
        self.db.commit()

        # Upsert without overriding credentials
        upsert_booru_config(self.db, "DANBOORU.DONMAI.US")
        self.db.commit()

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "danbooru.donmai.us")
        self.assertEqual(all_cfgs[0].username, "split_user")
        self.assertEqual(all_cfgs[0].api_key, "split_key")

    def test_delete_case_insensitive_and_cleans_duplicates(self):
        cfg1 = BooruConfig(
            domain="Danbooru.Donmai.Us",
            username="user1"
        )
        cfg2 = BooruConfig(
            domain="danbooru.donmai.us",
            username="user2"
        )
        self.db.add_all([cfg1, cfg2])
        self.db.commit()

        res = asyncio.run(delete_booru_config("https://DANBOORU.donmai.us/", current_user=self.user, db=self.db))
        self.assertEqual(res["status"], "success")

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 0)

    def test_get_booru_config_for_url_matches_normalized_config(self):
        req = BooruConfigCreate(
            domain="Danbooru.Donmai.Us",
            username="api_user",
            api_key="api_key"
        )
        asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))

        cfg = get_booru_config_for_url(self.db, "https://DANBOORU.donmai.us/posts/123")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.domain, "danbooru.donmai.us")
        self.assertEqual(cfg.username, "api_user")

    def test_get_booru_config_for_url_prefers_row_with_credentials_on_duplicate(self):
        cfg_blank = BooruConfig(
            domain="Danbooru.Donmai.Us",
            username=None,
            api_key=None
        )
        cfg_cred = BooruConfig(
            domain="danbooru.donmai.us",
            username="cred_user",
            api_key="cred_key"
        )
        self.db.add_all([cfg_blank, cfg_cred])
        self.db.commit()

        matched = get_booru_config_for_url(self.db, "https://danbooru.donmai.us/posts/100")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.username, "cred_user")
        self.assertEqual(matched.api_key, "cred_key")

    def test_backup_import_with_uppercase_and_unnormalized_urls(self):
        # Pre-insert existing mixed-case row with existing key
        existing_cfg = BooruConfig(
            domain="Danbooru.Donmai.Us",
            username="old_admin",
            api_key="old_api_key"
        )
        self.db.add(existing_cfg)
        self.db.commit()

        # Backup has uppercase scheme, path, query, and mixed casing
        backup_items = [
            {
                "domain": "HTTPS://DANBOORU.DONMAI.US/posts?filter=all/",
                "username": "imported_admin",
                "api_key": "imported_api_key"
            },
            {
                "domain": "http://GELBOORU.COM/",
                "username": "gel_user",
                "api_key": "gel_key"
            }
        ]

        result = import_booru_config_logical(self.db, backup_items)
        self.assertEqual(result["imported"], 2)

        # Danbooru was updated in-place and normalized
        dan_cfgs = self.db.query(BooruConfig).filter(BooruConfig.domain == "danbooru.donmai.us").all()
        self.assertEqual(len(dan_cfgs), 1)
        self.assertEqual(dan_cfgs[0].username, "imported_admin")
        self.assertEqual(dan_cfgs[0].api_key, "imported_api_key")

        # Gelbooru was created with clean lowercase hostname
        gel_cfg = self.db.query(BooruConfig).filter(BooruConfig.domain == "gelbooru.com").first()
        self.assertIsNotNone(gel_cfg)
        self.assertEqual(gel_cfg.domain, "gelbooru.com")
        self.assertEqual(gel_cfg.username, "gel_user")

        # Ensure no un-normalized domain remains
        all_domains = [c.domain for c in self.db.query(BooruConfig).all()]
        self.assertCountEqual(all_domains, ["danbooru.donmai.us", "gelbooru.com"])

if __name__ == "__main__":
    unittest.main()
