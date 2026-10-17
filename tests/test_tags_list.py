import asyncio

from backend.app.enums import TagCategoryEnum
from backend.app.models import Tag, TagAlias, User
from backend.app.routes.tags import get_tags_list
from tests.test_base import BackupTestBase

class TestTagsList(BackupTestBase):
    """Covers the /api/tags/list filtering, sorting, paging and payload shape."""

    def setUp(self):
        super().setUp()
        self.tags = {}
        seed = [
            ("cat_ears", TagCategoryEnum.general, 30),
            ("cat_tail", TagCategoryEnum.general, 30),
            ("catxears", TagCategoryEnum.general, 5),
            ("blomblo", TagCategoryEnum.artist, 10),
            ("original", TagCategoryEnum.copyright, 20),
            ("highres", TagCategoryEnum.meta, 40),
        ]
        for name, category, post_count in seed:
            tag = Tag(name=name, category=category, post_count=post_count)
            self.db.add(tag)
            self.tags[name] = tag
        self.db.commit()
        self.db.add(TagAlias(alias_name="nekomimi", target_tag_id=self.tags["cat_ears"].id))
        self.db.add(TagAlias(alias_name="catears", target_tag_id=self.tags["cat_ears"].id))
        self.db.commit()

    def _list(self, **overrides):
        params = dict(
            request=None, page=1, limit=50, sort="post_count", order="desc",
            q=None, categories=None, db=self.db
        )
        params.update(overrides)
        return asyncio.run(get_tags_list(**params))

    def _names(self, result):
        return [item.name if hasattr(item, "name") else item["name"] for item in result["items"]]

    def test_default_sort_and_payload(self):
        result = self._list()
        self.assertEqual(result["total"], 6)
        self.assertEqual(self._names(result)[0], "highres")
        item = next(i for i in result["items"] if i.name == "cat_ears")
        self.assertEqual(item.aliases, ["catears", "nekomimi"])
        self.assertEqual(item.category, TagCategoryEnum.general)

    def test_search_matches_underscore_literally(self):
        result = self._list(q="cat_ears")
        self.assertEqual(self._names(result), ["cat_ears"])

    def test_search_matches_alias(self):
        result = self._list(q="nekomimi")
        self.assertEqual(self._names(result), ["cat_ears"])

    def test_search_percent_is_literal(self):
        self.assertEqual(self._list(q="%")["total"], 0)

    def test_category_filter(self):
        result = self._list(categories="artist,meta")
        self.assertEqual(sorted(self._names(result)), ["blomblo", "highres"])

    def test_invalid_categories_return_nothing(self):
        self.assertEqual(self._list(categories="none")["total"], 0)
        self.assertEqual(self._list(categories="bogus,nope")["total"], 0)

    def test_invalid_category_mixed_with_valid_is_ignored(self):
        result = self._list(categories="artist,bogus")
        self.assertEqual(self._names(result), ["blomblo"])

    def test_blank_categories_means_no_filter(self):
        self.assertEqual(self._list(categories="  ")["total"], 6)

    def test_sort_by_id_ascending(self):
        result = self._list(sort="id", order="asc")
        ids = [i.id for i in result["items"]]
        self.assertEqual(ids, sorted(ids))

    def test_unknown_sort_falls_back_to_post_count(self):
        result = self._list(sort="uploaded_at")
        self.assertEqual(self._names(result)[0], "highres")

    def test_pagination_is_stable_with_ties(self):
        first = self._list(limit=1, page=1)
        second = self._list(limit=1, page=2)
        self.assertEqual(first["pages"], 6)
        self.assertNotEqual(self._names(first), self._names(second))
        both = [self.tags["cat_ears"].id, self.tags["cat_tail"].id]
        tied = self._list(q="cat_", sort="post_count", order="desc")
        self.assertEqual([i.id for i in tied["items"]], sorted(both, reverse=True))

    def test_page_below_one_is_clamped(self):
        result = self._list(page=-3)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["total"], 6)

    def test_include_aliases_false_returns_minimal_items(self):
        result = self._list(include_aliases=False)
        self.assertEqual(result["total"], 6)
        self.assertEqual(len(result["items"]), 6)
        item = result["items"][0]
        self.assertIn("id", item)
        self.assertIn("name", item)
        self.assertIn("category", item)
        self.assertNotIn("aliases", item)

    def test_high_limit_is_respected_without_aliases(self):
        result = self._list(limit=100000, include_aliases=False)
        self.assertEqual(result["limit"], 100000)
        self.assertEqual(result["total"], 6)
        self.assertEqual(len(result["items"]), 6)

    def test_high_limit_with_aliases_is_capped(self):
        result = self._list(limit=100000, include_aliases=True)
        self.assertEqual(result["limit"], 200)

    def test_slash_tag_route_matching(self):
        from backend.app.routes.tags import get_tag, router
        slash_tag = Tag(name="fate/grand_order", category=TagCategoryEnum.copyright, post_count=10)
        self.db.add(slash_tag)
        self.db.commit()

        # Direct function call
        res = asyncio.run(get_tag(request=None, tag_name="fate/grand_order", db=self.db))
        self.assertEqual(res.name, "fate/grand_order")

        # Starlette route dispatch with slashes
        scope_tag = {"type": "http", "method": "GET", "path": "/api/tags/fate/grand_order"}
        matching_tag = [r for r in router.routes if r.matches(scope_tag)[0].value == 2]
        self.assertEqual(len(matching_tag), 1)
        self.assertEqual(matching_tag[0].name, "get_tag")
        self.assertEqual(matching_tag[0].matches(scope_tag)[1]["path_params"], {"tag_name": "fate/grand_order"})

        scope_related = {"type": "http", "method": "GET", "path": "/api/tags/fate/grand_order/related"}
        matching_rel = [r for r in router.routes if r.matches(scope_related)[0].value == 2]
        self.assertEqual(len(matching_rel), 2)  # get_related_tags and fallback get_tag
        self.assertEqual(matching_rel[0].name, "get_related_tags")
        self.assertEqual(matching_rel[0].matches(scope_related)[1]["path_params"], {"tag_name": "fate/grand_order"})
