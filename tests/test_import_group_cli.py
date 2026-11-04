import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot.services.historical_import import ImportSummary
from scripts import import_group


class FakeTelegramClient:
    def __init__(self, *args):
        self.args = args

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeImporter:
    instances = []

    def __init__(self, *args):
        self.list_called = False
        self.scan_kwargs = None
        self.__class__.instances.append(self)

    async def list_topics(self, *, persist=True):
        self.list_called = True
        self.list_persist = persist
        return {5: "Courses"}

    async def scan(self, **kwargs):
        self.scan_kwargs = kwargs
        return ImportSummary()


def arguments(**changes):
    values = dict(list_topics=False, dry_run=False, preview=False, full_scan=False,
                  resume=False, report=False, topic_id=None, include_topics=None,
                  exclude_topics=None, limit=None, min_size=1, no_catalog=True)
    values.update(changes)
    return SimpleNamespace(**values)


class ImportGroupCommandPathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            telethon_session_path=Path(self.temp.name) / "session" / "vault",
            telegram_api_id=1, telegram_api_hash="hash", source_chat_id=-1001,
            database_path=Path(self.temp.name) / "db.sqlite", google_sheet_id=None,
            google_application_credentials=None, bot_username="test_bot",
            auto_approve_exact_matches=False,
            auto_sync_google_sheets=False,
        )
        FakeImporter.instances.clear()
        self.patches = (
            patch.object(import_group, "_telegram_client_type",
                         return_value=FakeTelegramClient),
            patch.object(import_group.ImportSettings, "from_env",
                         return_value=self.settings),
            patch.object(import_group, "HistoricalImporter", FakeImporter),
        )
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_list_topics_uses_topic_discovery_without_scanning(self):
        await import_group.run(arguments(list_topics=True))
        importer = FakeImporter.instances[-1]
        self.assertTrue(importer.list_called)
        self.assertFalse(importer.list_persist)
        self.assertIsNone(importer.scan_kwargs)

    async def test_dry_run_scans_without_persistence_mode(self):
        await import_group.run(arguments(dry_run=True, limit=25))
        self.assertEqual(
            {"topic_id": None, "limit": 25, "resume": False, "dry_run": True,
             "on_result": None},
            FakeImporter.instances[-1].scan_kwargs,
        )

    async def test_full_scan_uses_persistent_scan_mode(self):
        await import_group.run(arguments(full_scan=True))
        self.assertEqual(
            {"topic_id": None, "limit": None, "resume": False, "dry_run": False,
             "on_result": None},
            FakeImporter.instances[-1].scan_kwargs,
        )


if __name__ == "__main__":
    unittest.main()
