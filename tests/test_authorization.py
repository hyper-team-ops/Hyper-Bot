import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.admin import create_admin_handlers
from bot.middleware.authorization import is_admin
from bot.services.file_registry import FileRegistry


class AuthorizationTests(unittest.TestCase):
    def test_actual_user_id_is_required(self):
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=-10042))
        self.assertTrue(is_admin(update, {42}))
        self.assertFalse(is_admin(update, {-10042}))

    def test_missing_user_is_not_admin(self):
        self.assertFalse(is_admin(SimpleNamespace(effective_user=None), {42}))


class AdminHandlerAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_user_cannot_list_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteFileRepository(Path(directory) / "db.sqlite")
            settings = Settings(
                bot_token="test", bot_username="test_bot", source_channel_id=-1001,
                download_request_chat_id=-1002, complaint_recipient_chat_id=300,
                admin_user_ids=frozenset({42}), admin_chat_ids=frozenset(),
                database_url="sqlite:///unused", log_level="INFO",
                rate_limit_requests=5, rate_limit_window_seconds=60,
            )
            handlers = create_admin_handlers(
                settings, repository, FileRegistry(repository, -1001)
            )
            message = SimpleNamespace(reply_text=AsyncMock())
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=99), effective_message=message,
                callback_query=None,
            )
            await handlers["list"](update, SimpleNamespace(args=[]))
            self.assertIn("للمشرفين فقط", message.reply_text.await_args.args[0])
