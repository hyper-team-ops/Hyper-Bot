import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.constants import ChatType

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.flows import SEND_REQUEST
from bot.handlers.start import create_start_handler


class StartRequestFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_payload_enters_existing_request_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings("token", "bot", -1001, -1002, 4, frozenset({1}),
                                "sqlite:///unused", "INFO", 5, 60)
            repo = SQLiteFileRepository(Path(directory) / "db.sqlite")
            message = SimpleNamespace(chat_id=5, reply_text=AsyncMock())
            update = SimpleNamespace(effective_message=message,
                                     effective_chat=SimpleNamespace(id=5, type=ChatType.PRIVATE),
                                     effective_user=SimpleNamespace(id=5))
            context = SimpleNamespace(args=["request"], user_data={}, bot=AsyncMock())
            state = await create_start_handler(
                settings, repo, SimpleNamespace(deliver=AsyncMock()),
                SimpleNamespace(allow=lambda _: True),
            )(update, context)
            self.assertEqual(SEND_REQUEST, state)
            self.assertIn("أرسل اسم", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
