import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.constants import ChatType

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
            admin_user_ids=frozenset({1}),
            database_url="sqlite:///unused", log_level="INFO",
            rate_limit_requests=5, rate_limit_window_seconds=60,
        )

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    def context(self, args):
        return SimpleNamespace(args=args, user_data={"old": True}, bot=AsyncMock())

    def update(self):
        message = SimpleNamespace(chat_id=50, reply_text=AsyncMock())
        return SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=50),
            effective_chat=SimpleNamespace(id=50, type=ChatType.PRIVATE),
        ), message

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

    async def test_deep_link_in_group_never_delivers(self):
        record = FileRegistry(self.repository, -1001).register("group", "Group", [77])
        delivery = SimpleNamespace(deliver=AsyncMock())
        handler = create_start_handler(
            self.settings, self.repository, delivery,
            SimpleNamespace(allow=lambda _: True),
        )
        update, message = self.update()
        update.effective_chat.type = ChatType.SUPERGROUP
        await handler(update, self.context([record.public_token]))
        self.assertIn("المحادثة الخاصة", message.reply_text.await_args.args[0])
        delivery.deliver.assert_not_awaited()

    async def test_success_is_announced_only_after_delivery(self):
        record = FileRegistry(self.repository, -1001).register("ordered", "Ordered", [88])
        events = []

        async def deliver(*_args):
            events.append("delivered")
            return SimpleNamespace(complete=True)

        update, message = self.update()

        async def reply(*_args, **_kwargs):
            events.append("announced")

        message.reply_text.side_effect = reply
        handler = create_start_handler(
            self.settings,
            self.repository,
            SimpleNamespace(deliver=deliver),
            SimpleNamespace(allow=lambda _: True),
        )
        await handler(update, self.context([record.public_token]))
        self.assertEqual(["delivered", "announced"], events)
