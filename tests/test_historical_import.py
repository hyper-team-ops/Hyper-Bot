import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from bot.database.repository import SQLiteFileRepository
from bot.services.discovery import MessageFilter
from bot.services.historical_import import (
    HistoricalImporter,
    TelethonCompatibilityError,
    _get_forum_topics_request,
)
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


class ForumRequest:
    def __init__(self, **kwargs):
        if "channel" in kwargs or "peer" not in kwargs:
            raise TypeError("GetForumTopicsRequest requires peer")
        self.__dict__.update(kwargs)


class TopicClient(FakeClient):
    def __init__(self, pages):
        super().__init__([])
        self.pages = iter(pages)
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return next(self.pages)


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

    async def test_topic_discovery_uses_peer_and_count_aware_pagination(self):
        first_date = datetime(2026, 1, 2, tzinfo=UTC)
        second_date = datetime(2026, 1, 1, tzinfo=UTC)
        pages = [
            SimpleNamespace(
                count=3, order_by_create_date=False,
                topics=(SimpleNamespace(id=10, title="Ten", top_message=110),
                        SimpleNamespace(id=9, title="Nine", top_message=109)),
                messages=(SimpleNamespace(id=110, date=first_date),
                          SimpleNamespace(id=109, date=second_date)),
            ),
            SimpleNamespace(
                count=3, order_by_create_date=False,
                topics=(SimpleNamespace(id=8, title="Eight", top_message=108),),
                messages=(SimpleNamespace(id=108,
                                          date=datetime(2025, 12, 31, tzinfo=UTC)),),
            ),
        ]
        client = TopicClient(pages)
        importer = HistoricalImporter(
            client, self.repo,
            DiscoveryPipeline(self.repo, MessageFilter(), FileMatcher(), []), -1001,
            forum_topics_request=ForumRequest,
        )
        topics = await importer.list_topics()
        self.assertEqual({10: "Ten", 9: "Nine", 8: "Eight"}, topics)
        self.assertEqual(2, len(client.requests))
        self.assertEqual(-1001, client.requests[0].peer)
        self.assertEqual((second_date, 109, 9),
                         (client.requests[1].offset_date,
                          client.requests[1].offset_id,
                          client.requests[1].offset_topic))
        self.assertEqual(3, len(self.repo.list_topics(-1001)))

    async def test_topic_dry_run_does_not_persist_topic_metadata(self):
        page = SimpleNamespace(
            count=1, order_by_create_date=True,
            topics=(SimpleNamespace(id=5, title="Courses", top_message=50,
                                    date=datetime.now(UTC)),),
            messages=(),
        )
        client = TopicClient([page])
        importer = HistoricalImporter(
            client, self.repo,
            DiscoveryPipeline(self.repo, MessageFilter(), FileMatcher(), []), -1001,
            forum_topics_request=ForumRequest,
        )
        await importer.scan(dry_run=True, limit=0)
        self.assertEqual([], self.repo.list_topics(-1001))

    async def test_dry_run_and_full_scan_have_distinct_write_behavior(self):
        dry = self.importer(FakeClient([31]))
        dry_summary = await dry.scan(dry_run=True)
        self.assertEqual(1, dry_summary.processed)
        self.assertEqual([], self.repo.list_discovered())
        self.assertEqual((0, False), self.repo.get_checkpoint(-1001, None))

        full = self.importer(FakeClient([31]))
        full_summary = await full.scan(dry_run=False)
        self.assertEqual(1, full_summary.processed)
        self.assertEqual(1, len(self.repo.list_discovered()))
        self.assertEqual((31, True), self.repo.get_checkpoint(-1001, None))

    async def test_preview_callback_receives_every_result_without_writes(self):
        results = []
        summary = await self.importer(FakeClient([41, 42])).scan(
            dry_run=True, on_result=results.append
        )
        self.assertEqual(2, summary.processed)
        self.assertEqual([41, 42], [result.metadata.message_id for result in results])
        self.assertEqual([], self.repo.list_discovered())

    async def test_missing_generated_api_is_reported_as_incompatibility(self):
        telethon = SimpleNamespace(__version__="old-test")
        with patch(
            "bot.services.historical_import.importlib.import_module",
            side_effect=[telethon, ImportError("missing generated request")],
        ):
            with self.assertRaises(TelethonCompatibilityError) as caught:
                _get_forum_topics_request()
        self.assertIn("old-test", str(caught.exception))
        self.assertNotIn("not installed", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
