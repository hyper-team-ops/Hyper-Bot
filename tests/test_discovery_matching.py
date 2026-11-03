import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from bot.database.models import CatalogEntry, MatchStatus
from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter, ResourceMetadata, parse_telethon_message
from bot.services.matching import FileMatcher, normalize_filename
from bot.services.pipeline import DiscoveryPipeline


def metadata(**changes):
    values = dict(source_chat_id=-1001, message_id=10, topic_id=5,
                  topic_title="Design, adobe", filename="Photoshop_2025.zip",
                  caption=None, file_size=1024, mime_type="application/zip",
                  media_group_id=None, message_date=datetime.now(UTC), is_service=False)
    values.update(changes)
    return ResourceMetadata(**values)


def catalog(file_id="sw_photoshop", title="Adobe Photoshop"):
    return CatalogEntry(file_id, title, "1 KB", "Design", "zip", "softwares", 2)


class DiscoveryAndMatchingTests(unittest.TestCase):
    def test_filename_normalization_handles_versions_aliases_and_case(self):
        self.assertEqual("adobe photoshop", normalize_filename("Photoshop_2025.ZIP"))
        self.assertEqual("visual studio code", normalize_filename("VSCodeUserSetup-x64.exe"))

    def test_unique_strong_match_is_exact(self):
        result = FileMatcher().match(metadata(), [catalog()])
        self.assertEqual(MatchStatus.EXACT, result.status)
        self.assertEqual("sw_photoshop", result.entry.file_id)

    def test_similar_catalog_rows_are_ambiguous(self):
        entries = [catalog("one"), catalog("two")]
        self.assertEqual(MatchStatus.AMBIGUOUS,
                         FileMatcher().match(metadata(), entries).status)

    def test_unmatched_file_stays_unpublished(self):
        result = FileMatcher().match(metadata(filename="obscure-qzx.bin"), [catalog()])
        self.assertEqual(MatchStatus.UNMATCHED, result.status)
        self.assertIsNone(result.entry)

    def test_filter_uses_actual_topic_ids_and_ignores_text_and_services(self):
        filter_ = MessageFilter(included_topic_ids=frozenset({5}),
                                excluded_topic_ids=frozenset({9}))
        self.assertTrue(filter_.evaluate(metadata()).accepted)
        self.assertFalse(filter_.evaluate(metadata(topic_id=9)).accepted)
        self.assertFalse(filter_.evaluate(metadata(filename=None, mime_type=None)).accepted)
        self.assertFalse(filter_.evaluate(metadata(is_service=True)).accepted)

    def test_telethon_parser_extracts_metadata_without_download(self):
        reply = SimpleNamespace(reply_to_top_id=5, reply_to_msg_id=4, forum_topic=True)
        file = SimpleNamespace(name="course.zip", mime_type="application/zip", size=99)
        message = SimpleNamespace(id=44, reply_to=reply, file=file, document=None,
                                  photo=None, message="caption", grouped_id=7,
                                  date=datetime.now(UTC), action=None)
        item = parse_telethon_message(message, -1001, {5: "Courses"})
        self.assertEqual((5, "Courses", "course.zip", "7"),
                         (item.topic_id, item.topic_title, item.filename,
                          item.media_group_id))

    def test_pipeline_is_persistently_deduplicated_and_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteFileRepository(Path(directory) / "db.sqlite")
            pipeline = DiscoveryPipeline(repo, MessageFilter(), FileMatcher(), [catalog()])
            preview = pipeline.process(metadata(), dry_run=True)
            self.assertFalse(preview.duplicate)
            self.assertEqual([], repo.list_discovered())
            self.assertFalse(pipeline.process(metadata()).duplicate)
            self.assertTrue(pipeline.process(metadata()).duplicate)
            self.assertEqual(1, len(repo.list_candidates()))


if __name__ == "__main__":
    unittest.main()
