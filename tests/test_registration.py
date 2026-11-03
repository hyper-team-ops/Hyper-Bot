import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, MessageOriginChannel, MessageOriginChat
from telegram.constants import ChatType

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.admin import create_admin_handlers
from bot.services.file_delivery import DeliveryError, DeliveryResult
from bot.services.file_registry import FileRegistry
from bot.services.registration_drafts import RegistrationDraftStore


class ForwardedRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SQLiteFileRepository(Path(self.tempdir.name) / "db.sqlite")
        self.settings = Settings(
            bot_token="test", bot_username="test_bot", source_channel_id=-100100,
            download_request_chat_id=-1002, complaint_recipient_chat_id=300,
            admin_user_ids=frozenset({42}),
            database_url="sqlite:///unused", log_level="INFO",
            rate_limit_requests=5, rate_limit_window_seconds=60,
        )
        self.delivery = SimpleNamespace(deliver_messages=AsyncMock())
        self.delivery.deliver_messages.return_value = DeliveryResult(2, 2)
        self.handlers = create_admin_handlers(
            self.settings,
            self.repository,
            FileRegistry(self.repository, self.settings.source_channel_id),
            self.delivery,
            RegistrationDraftStore(),
        )
        self.message = SimpleNamespace(reply_text=AsyncMock(), forward_origin=None)
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42, type=ChatType.PRIVATE),
            effective_message=self.message,
            callback_query=None,
        )
        self.context = SimpleNamespace(args=[], bot=AsyncMock())

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    async def test_forwarded_multi_message_resource_is_verified_then_registered(self):
        self.context.args = ["album-2026", "Album", "2026"]
        await self.handlers["begin"](self.update, self.context)

        for message_id in (700, 701):
            self.message.forward_origin = MessageOriginChannel(
                date=datetime.now(UTC),
                chat=Chat(self.settings.source_channel_id, ChatType.CHANNEL),
                message_id=message_id,
            )
            await self.handlers["capture"](self.update, self.context)

        self.context.args = []
        await self.handlers["commit"](self.update, self.context)
        record = self.repository.get_by_website_id("album-2026")
        self.assertIsNotNone(record)
        self.assertEqual((700, 701), record.message_ids)
        self.delivery.deliver_messages.assert_awaited_once()
        call = self.delivery.deliver_messages.await_args.kwargs
        self.assertEqual(42, call["chat_id"])
        self.assertEqual((700, 701), call["message_ids"])

    async def test_forward_from_other_channel_is_rejected(self):
        self.context.args = ["wrong-source", "Wrong", "Source"]
        await self.handlers["begin"](self.update, self.context)
        self.message.forward_origin = MessageOriginChannel(
            date=datetime.now(UTC), chat=Chat(-100999, ChatType.CHANNEL),
            message_id=1,
        )
        await self.handlers["capture"](self.update, self.context)
        self.assertIn(
            "ليست معاد توجيهها",
            self.message.reply_text.await_args.args[0],
        )

    async def test_supergroup_forward_without_original_id_fails_safely(self):
        self.context.args = ["group-source", "Group", "Source"]
        await self.handlers["begin"](self.update, self.context)
        self.message.forward_origin = MessageOriginChat(
            date=datetime.now(UTC),
            sender_chat=Chat(self.settings.source_channel_id, ChatType.SUPERGROUP),
        )
        await self.handlers["capture"](self.update, self.context)
        self.assertIn("لا يرسل رقم الرسالة", self.message.reply_text.await_args.args[0])

    async def test_failed_copy_verification_is_not_persisted(self):
        self.context.args = ["unavailable", "Unavailable"]
        await self.handlers["begin"](self.update, self.context)
        self.message.forward_origin = MessageOriginChannel(
            date=datetime.now(UTC),
            chat=Chat(self.settings.source_channel_id, ChatType.CHANNEL),
            message_id=800,
        )
        await self.handlers["capture"](self.update, self.context)
        self.delivery.deliver_messages.side_effect = DeliveryError(
            "not copyable"
        )
        self.context.args = []
        await self.handlers["commit"](self.update, self.context)
        self.assertIsNone(self.repository.get_by_website_id("unavailable"))
