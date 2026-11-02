import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.config import Settings
from bot.handlers.flows import create_complaint_handler, create_request_handler


def settings():
    return Settings(
        bot_token="test", bot_username="test_bot", source_channel_id=-1001,
        download_request_chat_id=-1002, complaint_recipient_chat_id=300,
        admin_user_ids=frozenset({1}), admin_chat_ids=frozenset(),
        database_url="sqlite:///:memory:", log_level="INFO",
        rate_limit_requests=5, rate_limit_window_seconds=60,
    )


def update_with(text):
    message = SimpleNamespace(text=text, chat_id=555, reply_text=AsyncMock())
    return SimpleNamespace(effective_message=message), message


class ExistingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_request_reaches_configured_chat(self):
        update, message = update_with("كورس بايثون")
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await create_request_handler(settings())(update, context)
        context.bot.send_message.assert_awaited_once()
        self.assertEqual(-1002, context.bot.send_message.await_args.args[0])
        self.assertIn("كورس بايثون", context.bot.send_message.await_args.args[1])
        message.reply_text.assert_awaited_once()

    async def test_complaint_does_not_reveal_sender_identity(self):
        update, _ = update_with("اقتراح مجهول")
        update.effective_user = SimpleNamespace(id=999, username="secret")
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await create_complaint_handler(settings())(update, context)
        outgoing = context.bot.send_message.await_args.args[1]
        self.assertIn("اقتراح مجهول", outgoing)
        self.assertNotIn("999", outgoing)
        self.assertNotIn("secret", outgoing)
