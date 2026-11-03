import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType, SimpleNamespace

from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter
from bot.services.historical_import import HistoricalImporter
from bot.services.matching import FileMatcher
from bot.services.pipeline import DiscoveryPipeline


def telegram_message(message_id):
    return SimpleNamespace(
        id=message_id, reply_to=SimpleNamespace(reply_to_top_id=5,
                                                reply_to_msg_id=5,
                                                forum_topic=True),
        file=SimpleNamespace(name=f"file-{message_id}.zip",
                             mime_type="application/zip", size=100),
        document=None, photo=None, message=None, grouped_id=None,
        date=datetime.now(UTC), action=None,
    )


class FakeClient:
    def __init__(self, ids, cancel=False):
        self.ids, self.cancel = ids, cancel
        self.last_kwargs = None

    async def get_input_entity(self, chat_id):
        return chat_id

    def iter_messages(self, entity, **kwargs):
        self.last_kwargs = kwargs

        async def iterator():
            for index, message_id in enumerate(self.ids):
                if message_id > kwargs.get("min_id", 0):
                    yield telegram_message(message_id)
                    if self.cancel and index == 0:
                        raise asyncio.CancelledError
        return iterator()


class HistoricalImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = SQLiteFileRepository(Path(self.temp.name) / "db.sqlite")

    async def asyncTearDown(self):
        self.temp.cleanup()

    def importer(self, client):
        pipeline = DiscoveryPipeline(self.repo, MessageFilter(), FileMatcher(), [])
        importer = HistoricalImporter(client, self.repo, pipeline, -1001)

        async def topics(_self, *, persist=True):
            return {5: "Courses"}
        importer.list_topics = MethodType(topics, importer)
        return importer

    async def test_resume_starts_after_durable_checkpoint(self):
        self.repo.save_checkpoint(-1001, 5, 10)
        client = FakeClient([9, 11, 12])
        summary = await self.importer(client).scan(topic_id=5, resume=True)
        self.assertEqual(2, summary.processed)
        self.assertEqual(10, client.last_kwargs["min_id"])
        self.assertEqual((12, True), self.repo.get_checkpoint(-1001, 5))

    async def test_cancellation_saves_last_processed_message(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.importer(FakeClient([21, 22], cancel=True)).scan(topic_id=5)
        self.assertEqual((21, False), self.repo.get_checkpoint(-1001, 5))


if __name__ == "__main__":
    unittest.main()
