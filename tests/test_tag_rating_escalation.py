import asyncio
import io
from datetime import datetime

from starlette.datastructures import UploadFile

from backend.app.enums import FileTypeEnum, RatingEnum
from backend.app.models import Media, Tag, User
from backend.app.routes.admin.tags import MergeTagRequest, merge_tag
from backend.app.routes.media import bulk_update_tags, update_media
from backend.app.routes.uploads import (
    BulkUpdateRequest,
    bulk_update_staged_items,
    commit_upload_session,
    create_upload_session,
    update_staged_item,
    upload_files_to_session,
)
from backend.app.schemas import (
    BulkTagUpdateItem,
    BulkTagUpdateRequest,
    MediaUpdate,
    ProposedTag,
    UploadSessionItemUpdate,
)
from backend.app.utils.tag_utils import get_newly_added_tags
from tests.test_base import BackupTestBase, make_dummy_jpeg

class TestTagRatingEscalation(BackupTestBase):
    def setUp(self):
        super().setUp()
        self.admin = User(id=99, username="admin", password_hash="x")
        self.db.add(self.admin)
        for name, rating in [
            ("hot", RatingEnum.explicit),
            ("mild", RatingEnum.questionable),
            ("tame", RatingEnum.safe),
            ("plain", None),
        ]:
            self.db.add(Tag(name=name, rating=rating, post_count=0))
        self.db.commit()

    # -- helpers ---------------------------------------------------------
    def _media(self, name, rating, tag_names=()):
        media = Media(
            filename=name, path=f"media/original/{name}", thumbnail_path=f"t/{name}.jpg",
            hash=f"hash-{name}", file_type=FileTypeEnum.image, mime_type="image/jpeg",
            file_size=1, rating=rating, uploaded_at=datetime.now(),
        )
        media.tags = [self.db.query(Tag).filter_by(name=n).one() for n in tag_names]
        self.db.add(media)
        self.db.commit()
        self.db.refresh(media)
        return media

    def _update(self, media, **fields):
        asyncio.run(update_media(media_id=media.id, updates=MediaUpdate(**fields),
                                 current_user=self.admin, db=self.db))
        self.db.refresh(media)
        return media.rating

    # -- helper ----------------------------------------------------------
    def test_get_newly_added_tags(self):
        hot, tame = Tag(name="hot"), Tag(name="tame")
        self.assertEqual(get_newly_added_tags([hot], [hot, tame]), [tame])
        self.assertEqual(get_newly_added_tags([{"name": "Hot"}], [{"name": "hot"}, {"name": "x"}]), [{"name": "x"}])
        self.assertEqual(get_newly_added_tags(None, [hot]), [hot])
        self.assertEqual(get_newly_added_tags([hot], []), [])

    # -- update_media ----------------------------------------------------
    def test_added_tag_escalates_but_never_downgrades(self):
        media = self._media("a.jpg", RatingEnum.safe)
        self.assertEqual(self._update(media, tags=["mild"]), RatingEnum.questionable)
        self.assertEqual(self._update(media, tags=["mild", "hot"]), RatingEnum.explicit)
        self.assertEqual(self._update(media, tags=["mild", "hot", "tame"]), RatingEnum.explicit)

    def test_preexisting_tag_does_not_reescalate_manual_downgrade(self):
        media = self._media("b.jpg", RatingEnum.explicit, ["hot"])
        self.assertEqual(self._update(media, rating=RatingEnum.safe), RatingEnum.safe)
        # Editing tags later (adding an unrelated one) must not bring the rating back up.
        self.assertEqual(self._update(media, tags=["hot", "plain"]), RatingEnum.safe)
        self.assertEqual(self._update(media, tags=["hot", "plain", "tame"]), RatingEnum.safe)

    def test_removing_and_readding_tag_escalates_again(self):
        media = self._media("c.jpg", RatingEnum.safe, ["hot"])
        self.assertEqual(self._update(media, tags=["plain"]), RatingEnum.safe)
        self.assertEqual(self._update(media, tags=["plain", "hot"]), RatingEnum.explicit)

    def test_explicit_rating_in_same_request_wins(self):
        media = self._media("d.jpg", RatingEnum.explicit)
        self.assertEqual(self._update(media, rating=RatingEnum.safe, tags=["hot"]), RatingEnum.safe)

    # -- bulk_update_tags ------------------------------------------------
    def test_bulk_update_only_escalates_for_added_tags(self):
        fresh = self._media("e.jpg", RatingEnum.safe)
        lowered = self._media("f.jpg", RatingEnum.safe, ["hot"])  # already carries "hot"
        asyncio.run(bulk_update_tags(
            payload=BulkTagUpdateRequest(items=[
                BulkTagUpdateItem(id=fresh.id, tags=["mild"]),
                BulkTagUpdateItem(id=lowered.id, tags=["hot", "plain"]),
            ]),
            current_user=self.admin, db=self.db,
        ))
        self.db.refresh(fresh)
        self.db.refresh(lowered)
        self.assertEqual(fresh.rating, RatingEnum.questionable)
        self.assertEqual(lowered.rating, RatingEnum.safe)

    # -- merge -----------------------------------------------------------
    def test_merge_escalates_media_receiving_higher_rated_target(self):
        source = self.db.query(Tag).filter_by(name="plain").one()
        media = self._media("g.jpg", RatingEnum.safe, ["plain"])
        asyncio.run(merge_tag(tag_id=source.id, request_data=MergeTagRequest(target_tag_name="hot"),
                              db=self.db, current_user=self.admin))
        self.db.refresh(media)
        self.assertEqual([t.name for t in media.tags], ["hot"])
        self.assertEqual(media.rating, RatingEnum.explicit)

    def test_merge_does_not_downgrade_or_touch_media_already_on_target(self):
        source = self.db.query(Tag).filter_by(name="plain").one()
        higher = self._media("h.jpg", RatingEnum.explicit, ["plain"])
        already = self._media("i.jpg", RatingEnum.safe, ["plain", "mild"])  # target already attached
        asyncio.run(merge_tag(tag_id=source.id, request_data=MergeTagRequest(target_tag_name="mild"),
                              db=self.db, current_user=self.admin))
        self.db.refresh(higher)
        self.db.refresh(already)
        self.assertEqual(higher.rating, RatingEnum.explicit)
        self.assertEqual(already.rating, RatingEnum.safe)

    # -- upload staging --------------------------------------------------
    def _stage(self, session_id, filename, base_tags):
        return asyncio.run(upload_files_to_session(
            session_id=session_id, file=UploadFile(filename=filename, file=io.BytesIO(make_dummy_jpeg())),
            base_tags=base_tags, current_user=self.admin, db=self.db,
        ))

    def _new_session(self):
        return asyncio.run(create_upload_session(current_user=self.admin))["session_id"]

    def _update_staged(self, session_id, item_id, **fields):
        return asyncio.run(update_staged_item(
            session_id=session_id, item_id=item_id, update=UploadSessionItemUpdate(**fields),
            current_user=self.admin, db=self.db,
        ))

    def _commit_rating(self, session_id):
        res = asyncio.run(commit_upload_session(session_id=session_id, current_user=self.admin, db=self.db))
        self.assertEqual(res.total_failed, 0)
        return self.db.query(Media).filter(Media.id == res.results[0].media_id).one().rating

    def test_initial_staging_escalates_from_tags(self):
        sid = self._new_session()
        item = self._stage(sid, "j.jpg", "hot")
        self.assertEqual(item["rating"], "explicit")
        self.assertEqual(self._commit_rating(sid), RatingEnum.explicit)

    def test_staged_manual_downgrade_survives_commit(self):
        sid = self._new_session()
        item = self._stage(sid, "k.jpg", "hot")
        lowered = self._update_staged(sid, item["item_id"], rating=RatingEnum.safe)
        self.assertEqual(lowered["rating"], "safe")
        self.assertEqual(self._commit_rating(sid), RatingEnum.safe)

    def test_staged_tag_update_escalates_only_for_new_tags(self):
        sid = self._new_session()
        item = self._stage(sid, "l.jpg", "hot")
        lowered = self._update_staged(sid, item["item_id"], rating=RatingEnum.safe)
        names = [t["name"] for t in lowered["tags"]]
        # Re-saving the same tags plus an unrelated one keeps the manual rating...
        kept = self._update_staged(sid, item["item_id"], tags=[ProposedTag(name=n) for n in names + ["plain"]])
        self.assertEqual(kept["rating"], "safe")
        # ...while a genuinely new higher-rated tag escalates a lower rating.
        mid = self._update_staged(sid, item["item_id"], rating=RatingEnum.safe,
                                  tags=[ProposedTag(name=n) for n in ["plain"]])
        self.assertEqual(mid["rating"], "safe")
        esc = self._update_staged(sid, item["item_id"], tags=[ProposedTag(name=n) for n in ["plain", "mild"]])
        self.assertEqual(esc["rating"], "questionable")

    def test_staged_explicit_rating_in_same_request_wins(self):
        sid = self._new_session()
        item = self._stage(sid, "m.jpg", "plain")
        res = self._update_staged(sid, item["item_id"], rating=RatingEnum.safe,
                                  tags=[ProposedTag(name="plain"), ProposedTag(name="hot")])
        self.assertEqual(res["rating"], "safe")

    def test_bulk_staged_update(self):
        sid = self._new_session()
        item = self._stage(sid, "n.jpg", "plain")
        res = asyncio.run(bulk_update_staged_items(
            session_id=sid, req=BulkUpdateRequest(item_ids=[item["item_id"]], add_tags=["hot"]),
            current_user=self.admin, db=self.db))
        self.assertEqual(res["items"][0]["rating"], "explicit")
        # A rating-only bulk change is never re-escalated by tags the item already had.
        res = asyncio.run(bulk_update_staged_items(
            session_id=sid, req=BulkUpdateRequest(item_ids=[item["item_id"]], rating=RatingEnum.safe),
            current_user=self.admin, db=self.db))
        self.assertEqual(res["items"][0]["rating"], "safe")
        self.assertEqual(self._commit_rating(sid), RatingEnum.safe)
