import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from bot.database.models import CatalogEntry, MatchStatus
from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter, ResourceMetadata, parse_telethon_message
from bot.services.matching import (
    FileMatcher,
    _size_bytes,
    normalize_filename,
    parse_telegram_source_url,
)
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

    def test_malformed_catalog_size_is_ignored_instead_of_crashing(self):
        self.assertIsNone(_size_bytes("2..7 GB"))
        self.assertEqual(2 * 1024**3, _size_bytes("2 GB"))

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

    def test_direct_public_source_url_wins_over_filename_similarity(self):
        linked = CatalogEntry(
            None, "Chrome", "127 MB", "Browsers",
            "https://t.me/Hyper_Vault/84/133", "softwares", 2,
        )
        misleading = catalog("wrong", "google chrome hyper team")
        result = FileMatcher(
            source_chat_id=-100123, source_username="Hyper_Vault"
        ).match(
            metadata(message_id=133, topic_id=84,
                     filename="google-chrome-134.zip"),
            [misleading, linked],
        )
        self.assertEqual(MatchStatus.EXACT, result.status)
        self.assertIs(linked, result.entry)
        self.assertIn("Telegram URL", result.reason)

    def test_private_source_url_is_validated_against_configured_group(self):
        valid = CatalogEntry(None, "Opera", None, None,
                             "https://t.me/c/123/84/134", "softwares", 3)
        wrong = CatalogEntry(None, "Opera", None, None,
                             "https://t.me/c/999/84/134", "softwares", 4)
        item = metadata(message_id=134, topic_id=84, filename="Opera.zip")
        matcher = FileMatcher(source_chat_id=-100123)
        self.assertIs(valid, matcher.match(item, [valid]).entry)
        self.assertNotEqual("exact configured-source Telegram URL match",
                            matcher.match(item, [wrong]).reason)

    def test_duplicate_direct_source_links_require_review(self):
        first = CatalogEntry("one", "Opera", None, None,
                             "https://t.me/Hyper_Vault/84/134", "softwares", 3)
        second = CatalogEntry("two", "Opera duplicate", None, None,
                              "https://t.me/Hyper_Vault/84/134", "softwares", 30)
        result = FileMatcher(
            source_chat_id=-100123, source_username="Hyper_Vault"
        ).match(metadata(message_id=134, topic_id=84), [first, second])
        self.assertEqual(MatchStatus.AMBIGUOUS, result.status)
        self.assertIn("duplicate catalog rows", result.reason)

    def test_source_url_parser_rejects_youtube_deep_links_and_bad_parts(self):
        self.assertEqual(
            (84, 133),
            (parse_telegram_source_url(
                "https://t.me/Hyper_Vault/84/133"
            ).topic_id,
             parse_telegram_source_url(
                 "https://t.me/Hyper_Vault/84/133"
             ).message_id),
        )
        self.assertIsNone(parse_telegram_source_url("https://youtu.be/abc"))
        self.assertIsNone(parse_telegram_source_url(
            "https://t.me/HyperTeamITE_Bot?start=f_token"
        ))
        self.assertEqual(
            133,
            parse_telegram_source_url(
                "https://t.me/Hyper_Vault/84/133?single"
            ).message_id,
        )

    def test_existing_approved_source_mapping_precedes_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteFileRepository(Path(directory) / "db.sqlite")
            repo.create(website_id="stable", title="Stable", public_token="f_test",
                        source_channel_id=-1001, message_ids=(10,))
            stable = catalog("stable", "Unrelated stable title")
            other = catalog("other", "Adobe Photoshop")
            pipeline = DiscoveryPipeline(repo, MessageFilter(), FileMatcher(),
                                         [other, stable])
            result = pipeline.process(metadata(), dry_run=True)
            self.assertEqual("stable", result.match.entry.file_id)
            self.assertIn("existing approved", result.match.reason)


if __name__ == "__main__":
    unittest.main()
