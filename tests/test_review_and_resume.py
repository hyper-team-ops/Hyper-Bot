import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.database.models import CatalogEntry
from bot.database.repository import SQLiteFileRepository
from bot.services.file_registry import FileRegistry
from bot.services.review import ReviewService


class ReviewAndResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = SQLiteFileRepository(Path(self.temp.name) / "db.sqlite")
        self.entry = CatalogEntry("course_abc", "Python Course", None, "Courses", "zip",
                                  "courses", 4)
        self.service = ReviewService(self.repo, FileRegistry(self.repo, -1001),
                                     [self.entry], "test_bot")

    def tearDown(self):
        self.temp.cleanup()

    def add_candidate(self, message_id, *, group=None, offset=0):
        item, _ = self.repo.add_discovered_message(
            source_chat_id=-1001, message_id=message_id, topic_id=8,
            topic_title="Courses", filename=f"part-{message_id}.zip", caption=None,
            file_size=10, mime_type="application/zip", media_group_id=group,
            message_date=datetime.now(UTC) + timedelta(seconds=offset),
        )
        return self.repo.add_match_candidate(
            discovered_message_id=item.id, website_file_id=self.entry.file_id,
            website_title=self.entry.title, confidence=.95, status="exact",
        )

    def test_approval_registers_ordered_album_and_is_idempotent(self):
        first = self.add_candidate(101, group="album", offset=0)
        self.add_candidate(102, group="album", offset=1)
        result = self.service.approve(first.id, 42)
        self.assertEqual((101, 102), result.record.message_ids)
        repeated = self.service.approve(first.id, 42)
        self.assertEqual(result.record.public_token, repeated.record.public_token)

    def test_explicit_multipart_grouping_preserves_admin_order_by_date(self):
        first = self.add_candidate(201, offset=1)
        second = self.add_candidate(200, offset=0)
        result = self.service.approve(first.id, 42,
                                      discovered_ids=(first.discovered_message_id,
                                                      second.discovered_message_id))
        self.assertEqual((200, 201), result.record.message_ids)

    def test_rejected_and_ignored_candidates_leave_pending_queue(self):
        rejected = self.add_candidate(301)
        ignored = self.add_candidate(302)
        self.service.reject(rejected.id, 42)
        self.service.ignore(ignored.id, 42)
        self.assertEqual([], self.repo.list_candidates())
        self.assertEqual(1, len(self.repo.list_candidates(statuses=("rejected",))))
        self.service.reconsider(ignored.id)
        self.assertEqual("ambiguous", self.repo.get_candidate(ignored.id).status)

    def test_checkpoint_survives_repository_restart(self):
        self.repo.save_checkpoint(-1001, 8, 777)
        reopened = SQLiteFileRepository(Path(self.temp.name) / "db.sqlite")
        self.assertEqual((777, False), reopened.get_checkpoint(-1001, 8))

    def test_approval_preserves_existing_public_token(self):
        record = FileRegistry(self.repo, -1001).register("course_abc", "Old", [500])
        candidate = self.add_candidate(501)
        updated = self.service.approve(candidate.id, 42).record
        self.assertEqual(record.public_token, updated.public_token)
        self.assertEqual((501,), updated.message_ids)

    def test_source_link_match_without_stable_file_id_cannot_be_approved(self):
        item, _ = self.repo.add_discovered_message(
            source_chat_id=-1001, message_id=601, topic_id=8,
            topic_title="Courses", filename="course.zip", caption=None,
            file_size=10, mime_type="application/zip", media_group_id=None,
            message_date=datetime.now(UTC),
        )
        candidate = self.repo.add_match_candidate(
            discovered_message_id=item.id, website_file_id=None,
            website_title="Course without ID", confidence=1.0, status="exact",
            reason="exact configured-source Telegram URL match",
        )
        with self.assertRaisesRegex(ValueError, "File ID"):
            self.service.approve(candidate.id, 42)
        self.assertEqual([], self.repo.list())


if __name__ == "__main__":
    unittest.main()
