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
        self.assertEqual(normalize_domain("https://Booru.Example.Com/"), "booru.example.com")
        self.assertEqual(normalize_domain("https://Booru.Example.Com/posts/100?q=test#tag"), "booru.example.com")
        self.assertEqual(normalize_domain("Booru.Example.Com"), "booru.example.com")
        self.assertEqual(normalize_domain("http://[::1]:8080/data/test.jpg"), "[::1]:8080")
        self.assertEqual(normalize_domain("[::1]:8080"), "[::1]:8080")
        self.assertEqual(normalize_domain("booru.example.com:8080/"), "booru.example.com:8080")
        self.assertEqual(normalize_domain("   https://SAFEBOORU.EXAMPLE.COM/   "), "safebooru.example.com")
        self.assertEqual(normalize_domain(""), "")
        self.assertEqual(normalize_domain(None), "")

    def test_create_normalizes_domain_to_lowercase(self):
        req = BooruConfigCreate(
            domain="https://Booru.Example.Com/",
            username="admin_user",
            api_key="secret123"
        )
        res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
        self.assertEqual(res.domain, "booru.example.com")

        # Verify stored in DB with normalized lowercase
        db_cfg = self.db.query(BooruConfig).first()
        self.assertIsNotNone(db_cfg)
        self.assertEqual(db_cfg.domain, "booru.example.com")
        self.assertEqual(db_cfg.username, "admin_user")

    def test_update_matches_existing_mixed_case_and_normalizes_it(self):
        # Insert a pre-existing mixed-case record into DB
        legacy_cfg = BooruConfig(
            domain="Booru.Example.Com",
            username="old_user",
            api_key="old_key"
        )
        self.db.add(legacy_cfg)
        self.db.commit()

        # Update with lowercase domain
        req = BooruConfigCreate(
            domain="booru.example.com",
            username="new_user",
            api_key="new_key"
        )
        res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
        self.assertEqual(res.domain, "booru.example.com")
        self.assertEqual(res.username, "new_user")

        # Ensure no duplicate record exists
        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "booru.example.com")
        self.assertEqual(all_cfgs[0].username, "new_user")

    def test_update_when_case_duplicates_exist_deduplicates_and_preserves_credentials(self):
        # Insert two records differing only by case:
        # One has mixed case and real credentials, the other is normalized but empty
        cfg_mixed = BooruConfig(
            domain="Safebooru.Example.Com",
            username="real_user",
            api_key="secret_key"
        )
        cfg_lower = BooruConfig(
            domain="safebooru.example.com",
            username=None,
            api_key=None
        )
        self.db.add_all([cfg_mixed, cfg_lower])
        self.db.commit()

        # Update unrelated field or re-save without providing new api_key
        req = BooruConfigCreate(
            domain="safebooru.example.com",
            username="updated_user",
            api_key=None
        )
        with patch("backend.app.services.booru.factory.logger.warning") as mock_warn:
            res = asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))
            mock_warn.assert_called_once()

        self.assertEqual(res.domain, "safebooru.example.com")
        self.assertTrue(res.has_api_key)

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "safebooru.example.com")
        self.assertEqual(all_cfgs[0].username, "updated_user")
        self.assertEqual(all_cfgs[0].api_key, "secret_key")

    def test_merge_coalesces_split_credentials(self):
        # One duplicate has username, the other has api_key
        cfg1 = BooruConfig(
            domain="Booru.Example.Com",
            username="split_user",
            api_key=None
        )
        cfg2 = BooruConfig(
            domain="booru.example.com",
            username=None,
            api_key="split_key"
        )
        self.db.add_all([cfg1, cfg2])
        self.db.commit()

        # Upsert without overriding credentials
        upsert_booru_config(self.db, "BOORU.EXAMPLE.COM")
        self.db.commit()

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 1)
        self.assertEqual(all_cfgs[0].domain, "booru.example.com")
        self.assertEqual(all_cfgs[0].username, "split_user")
        self.assertEqual(all_cfgs[0].api_key, "split_key")

    def test_delete_case_insensitive_and_cleans_duplicates(self):
        cfg1 = BooruConfig(
            domain="Booru.Example.Com",
            username="user1"
        )
        cfg2 = BooruConfig(
            domain="booru.example.com",
            username="user2"
        )
        self.db.add_all([cfg1, cfg2])
        self.db.commit()

        res = asyncio.run(delete_booru_config("https://BOORU.example.com/", current_user=self.user, db=self.db))
        self.assertEqual(res["status"], "success")

        all_cfgs = self.db.query(BooruConfig).all()
        self.assertEqual(len(all_cfgs), 0)

    def test_get_booru_config_for_url_matches_normalized_config(self):
        req = BooruConfigCreate(
            domain="Booru.Example.Com",
            username="api_user",
            api_key="api_key"
        )
        asyncio.run(create_or_update_booru_config(req, current_user=self.user, db=self.db))

        cfg = get_booru_config_for_url(self.db, "https://BOORU.example.com/posts/123")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.domain, "booru.example.com")
        self.assertEqual(cfg.username, "api_user")

    def test_get_booru_config_for_url_prefers_row_with_credentials_on_duplicate(self):
        cfg_blank = BooruConfig(
            domain="Booru.Example.Com",
            username=None,
            api_key=None
        )
        cfg_cred = BooruConfig(
            domain="booru.example.com",
            username="cred_user",
            api_key="cred_key"
        )
        self.db.add_all([cfg_blank, cfg_cred])
        self.db.commit()

        matched = get_booru_config_for_url(self.db, "https://booru.example.com/posts/100")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.username, "cred_user")
        self.assertEqual(matched.api_key, "cred_key")

    def test_backup_import_with_uppercase_and_unnormalized_urls(self):
        # Pre-insert existing mixed-case row with existing key
        existing_cfg = BooruConfig(
            domain="Booru.Example.Com",
            username="old_admin",
            api_key="old_api_key"
        )
        self.db.add(existing_cfg)
        self.db.commit()

        # Backup has uppercase scheme, path, query, and mixed casing
        backup_items = [
            {
                "domain": "HTTPS://BOORU.EXAMPLE.COM/posts?filter=all/",
                "username": "imported_admin",
                "api_key": "imported_api_key"
            },
            {
                "domain": "http://OTHERBOORU.EXAMPLE.COM/",
                "username": "other_user",
                "api_key": "other_key"
            }
        ]

        result = import_booru_config_logical(self.db, backup_items)
        self.assertEqual(result["imported"], 2)

        # Booru was updated in-place and normalized
        booru_cfgs = self.db.query(BooruConfig).filter(BooruConfig.domain == "booru.example.com").all()
        self.assertEqual(len(booru_cfgs), 1)
        self.assertEqual(booru_cfgs[0].username, "imported_admin")
        self.assertEqual(booru_cfgs[0].api_key, "imported_api_key")

        # Otherbooru was created with clean lowercase hostname
        other_cfg = self.db.query(BooruConfig).filter(BooruConfig.domain == "otherbooru.example.com").first()
        self.assertIsNotNone(other_cfg)
        self.assertEqual(other_cfg.domain, "otherbooru.example.com")
        self.assertEqual(other_cfg.username, "other_user")

        # Ensure no un-normalized domain remains
        all_domains = [c.domain for c in self.db.query(BooruConfig).all()]
        self.assertCountEqual(all_domains, ["booru.example.com", "otherbooru.example.com"])

if __name__ == "__main__":
    unittest.main()
