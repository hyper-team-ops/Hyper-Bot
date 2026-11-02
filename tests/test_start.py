import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.start import create_start_handler
from bot.services.file_registry import FileRegistry


class StartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SQLiteFileRepository(Path(self.tempdir.name) / "db.sqlite")
        self.settings = Settings(
            bot_token="test", bot_username="test_bot", source_channel_id=-1001,
            download_request_chat_id=-1002, complaint_recipient_chat_id=300,
            admin_user_ids=frozenset({1}), admin_chat_ids=frozenset(),
            database_url="sqlite:///unused", log_level="INFO",
            rate_limit_requests=5, rate_limit_window_seconds=60,
        )

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    def context(self, args):
        return SimpleNamespace(args=args, user_data={"old": True}, bot=AsyncMock())

    def update(self):
        message = SimpleNamespace(chat_id=50, reply_text=AsyncMock())
        return SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=50)), message

    async def test_start_without_argument_opens_menu(self):
        delivery = SimpleNamespace(deliver=AsyncMock())
        limiter = SimpleNamespace(allow=lambda _: True)
        handler = create_start_handler(self.settings, self.repository, delivery, limiter)
        update, message = self.update()
        await handler(update, self.context([]))
        self.assertIn("أهلاً", message.reply_text.await_args.args[0])
        delivery.deliver.assert_not_awaited()

    async def test_valid_token_delivers_correct_record(self):
        record = FileRegistry(self.repository, -1001).register("course", "Course", [77])
        delivery = SimpleNamespace(deliver=AsyncMock())
        handler = create_start_handler(
            self.settings, self.repository, delivery, SimpleNamespace(allow=lambda _: True)
        )
        update, _ = self.update()
        context = self.context([record.public_token])
        await handler(update, context)
        delivered_record = delivery.deliver.await_args.args[2]
        self.assertEqual((77,), delivered_record.message_ids)

    async def test_invalid_token_does_not_deliver(self):
        delivery = SimpleNamespace(deliver=AsyncMock())
        handler = create_start_handler(
            self.settings, self.repository, delivery, SimpleNamespace(allow=lambda _: True)
        )
        update, message = self.update()
        await handler(update, self.context(["invalid"]))
        self.assertIn("غير متوفر", message.reply_text.await_args.args[0])
        delivery.deliver.assert_not_awaited()
