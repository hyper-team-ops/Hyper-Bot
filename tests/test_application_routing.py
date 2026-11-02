import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegram import (
    CallbackQuery, Chat, Message, MessageEntity, Update, User,
)
from telegram.constants import ChatType
from telegram.ext import ExtBot

from bot.config import Settings
from bot.keyboards.keyboards import COMPLAINT, DOWNLOAD_REQUEST
from bot.main import build_application
from bot.services.file_registry import FileRegistry


class ApplicationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            bot_token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
            bot_username="test_bot",
            source_channel_id=-1001,
            download_request_chat_id=-1002,
            complaint_recipient_chat_id=300,
            admin_user_ids=frozenset({42}),
            database_url=f"sqlite:///{self.tempdir.name}/routing.db",
            log_level="INFO",
            rate_limit_requests=5,
            rate_limit_window_seconds=60,
        )
        self.application = build_application(self.settings)
        self.application._initialized = True
        with self.application.bot._unfrozen():
            self.application.bot._bot_user = User(
                id=999, is_bot=True, first_name="Bot", username="test_bot"
            )
        self.send_message = AsyncMock(side_effect=self._sent_message)
        self.answer_callback = AsyncMock(return_value=True)
        self.edit_message = AsyncMock(side_effect=self._edited_message)
        self.copy_message = AsyncMock(return_value=object())
        self.copy_messages = AsyncMock(return_value=(object(),))
        self.patchers = [
            patch.object(ExtBot, "send_message", self.send_message),
            patch.object(
                ExtBot, "answer_callback_query", self.answer_callback
            ),
            patch.object(ExtBot, "edit_message_text", self.edit_message),
            patch.object(ExtBot, "copy_message", self.copy_message),
            patch.object(ExtBot, "copy_messages", self.copy_messages),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.update_id = 0

    async def asyncTearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tempdir.cleanup()

    def _sent_message(self, *args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else 0)
        text = kwargs.get("text", args[1] if len(args) > 1 else "")
        chat_type = ChatType.PRIVATE if chat_id > 0 else ChatType.SUPERGROUP
        message = Message(
            message_id=900 + self.update_id,
            date=datetime.now(UTC),
            chat=Chat(chat_id, chat_type),
            text=text,
        )
        message.set_bot(self.application.bot)
        return message

    def _edited_message(self, *args, **kwargs):
        return self._sent_message(
            chat_id=kwargs.get("chat_id", 42), text=kwargs.get("text", "")
        )

    def text_update(self, text: str, *, user_id: int = 50) -> Update:
        self.update_id += 1
        message = Message(
            message_id=self.update_id,
            date=datetime.now(UTC),
            chat=Chat(user_id, ChatType.PRIVATE),
            from_user=User(user_id, False, "User"),
            text=text,
        )
        message.set_bot(self.application.bot)
        return Update(self.update_id, message=message)

    def command_update(self, command: str, *, user_id: int = 50) -> Update:
        self.update_id += 1
        message = Message(
            message_id=self.update_id,
            date=datetime.now(UTC),
            chat=Chat(user_id, ChatType.PRIVATE),
            from_user=User(user_id, False, "User"),
            text=command,
            entities=(
                MessageEntity(
                    MessageEntity.BOT_COMMAND,
                    0,
                    len(command.split(" ", 1)[0]),
                ),
            ),
        )
        message.set_bot(self.application.bot)
        return Update(self.update_id, message=message)

    def callback_update(self, data: str, *, user_id: int = 42) -> Update:
        self.update_id += 1
        message = Message(
            message_id=self.update_id,
            date=datetime.now(UTC),
            chat=Chat(user_id, ChatType.PRIVATE),
            text="admin menu",
        )
        message.set_bot(self.application.bot)
        query = CallbackQuery(
            id=f"query-{self.update_id}",
            from_user=User(user_id, False, "Admin"),
            chat_instance="test",
            message=message,
            data=data,
        )
        query.set_bot(self.application.bot)
        return Update(self.update_id, callback_query=query)

    async def test_download_request_response_reaches_active_state(self):
        await self.application.process_update(self.text_update(DOWNLOAD_REQUEST))
        await self.application.process_update(self.text_update("كورس بايثون"))

        destination_calls = [
            call for call in self.send_message.await_args_list
            if call.args and call.args[0] == self.settings.download_request_chat_id
        ]
        self.assertEqual(1, len(destination_calls))
        self.assertIn("كورس بايثون", destination_calls[0].args[1])
        all_text = "\n".join(
            str(call.kwargs.get("text", call.args[1] if len(call.args) > 1 else ""))
            for call in self.send_message.await_args_list
        )
        self.assertNotIn("أمر غير صالح", all_text)

    async def test_complaint_response_reaches_active_state_anonymously(self):
        await self.application.process_update(self.text_update(COMPLAINT))
        # Even text equal to a menu choice must be treated as complaint content while
        # this conversation state is active.
        await self.application.process_update(self.text_update(DOWNLOAD_REQUEST))

        destination_calls = [
            call for call in self.send_message.await_args_list
            if call.args and call.args[0] == self.settings.complaint_recipient_chat_id
        ]
        self.assertEqual(1, len(destination_calls))
        self.assertIn(DOWNLOAD_REQUEST, destination_calls[0].args[1])
        self.assertNotIn("50", destination_calls[0].args[1])

    async def test_admin_message_response_reaches_admin_state(self):
        await self.application.process_update(
            self.command_update("/start", user_id=42)
        )
        await self.application.process_update(
            self.callback_update("admin:message", user_id=42)
        )
        await self.application.process_update(
            self.text_update("777 مرحباً", user_id=42)
        )

        direct_calls = [
            call for call in self.send_message.await_args_list
            if call.args and call.args[0] == 777
        ]
        self.assertEqual(1, len(direct_calls))
        self.assertEqual("مرحباً", direct_calls[0].args[1])

    async def test_cancel_remains_available_inside_conversation(self):
        await self.application.process_update(self.text_update(DOWNLOAD_REQUEST))
        await self.application.process_update(self.command_update("/cancel"))
        await self.application.process_update(self.text_update("لن يرسل كطلب"))

        request_calls = [
            call for call in self.send_message.await_args_list
            if call.args and call.args[0] == self.settings.download_request_chat_id
        ]
        self.assertEqual([], request_calls)
        self.assertTrue(
            any(
                "تم الإلغاء" in str(call.kwargs.get("text", ""))
                for call in self.send_message.await_args_list
            )
        )

    async def test_start_remains_available_inside_conversation(self):
        await self.application.process_update(self.text_update(DOWNLOAD_REQUEST))
        await self.application.process_update(self.command_update("/start"))
        await self.application.process_update(self.text_update("ليس طلباً"))

        request_calls = [
            call for call in self.send_message.await_args_list
            if call.args and call.args[0] == self.settings.download_request_chat_id
        ]
        self.assertEqual([], request_calls)
        self.assertTrue(
            any(
                "أهلاً" in str(call.kwargs.get("text", ""))
                for call in self.send_message.await_args_list
            )
        )

    async def test_private_deep_link_copies_then_announces_success(self):
        repository = self.application.bot_data["repository"]
        record = FileRegistry(
            repository, self.settings.source_channel_id
        ).register("routing-file", "Routing File", [321])
        update = self.command_update(f"/start {record.public_token}")
        # Only `/start` is the command entity; the remainder is its argument.
        await self.application.process_update(update)

        self.copy_message.assert_awaited_once_with(
            chat_id=50,
            from_chat_id=self.settings.source_channel_id,
            message_id=321,
            caption="",
        )
        self.assertIn(
            "تم إرسال الملف",
            self.send_message.await_args_list[-1].kwargs["text"],
        )

    async def test_group_deep_link_never_copies(self):
        repository = self.application.bot_data["repository"]
        record = FileRegistry(
            repository, self.settings.source_channel_id
        ).register("group-file", "Group File", [654])
        self.update_id += 1
        text = f"/start {record.public_token}"
        message = Message(
            message_id=self.update_id,
            date=datetime.now(UTC),
            chat=Chat(-500, ChatType.SUPERGROUP),
            from_user=User(50, False, "User"),
            text=text,
            entities=(MessageEntity(MessageEntity.BOT_COMMAND, 0, 6),),
        )
        message.set_bot(self.application.bot)
        await self.application.process_update(Update(self.update_id, message=message))

        self.copy_message.assert_not_awaited()
        self.copy_messages.assert_not_awaited()
        self.assertIn(
            "المحادثة الخاصة",
            self.send_message.await_args_list[-1].kwargs["text"],
        )
