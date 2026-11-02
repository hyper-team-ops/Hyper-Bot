import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot.database.models import FileRecord
from bot.services.file_delivery import DeliveryError, FileDeliveryService


def record(*message_ids):
    now = datetime.now(UTC)
    return FileRecord(
        id=1, website_id="x", title="Example", public_token="f_" + "x" * 24,
        source_channel_id=-100999, message_ids=message_ids, file_type=None,
        description=None, active=True, strip_captions=True,
        created_at=now, updated_at=now,
    )


def album_record(*message_ids):
    item = record(*message_ids)
    return FileRecord(
        id=item.id, website_id=item.website_id, title=item.title,
        public_token=item.public_token, source_channel_id=item.source_channel_id,
        message_ids=item.message_ids, file_type=item.file_type,
        description=item.description, active=item.active, strip_captions=False,
        created_at=item.created_at, updated_at=item.updated_at,
    )


class FileDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_messages_are_copied_in_order_without_forwarding(self):
        bot = AsyncMock()
        result = await FileDeliveryService().deliver(bot, 777, record(9, 7, 8))
        self.assertTrue(result.complete)
        self.assertEqual([9, 7, 8], [call.kwargs["message_id"] for call in bot.copy_message.await_args_list])
        self.assertTrue(all(call.kwargs["from_chat_id"] == -100999 for call in bot.copy_message.await_args_list))
        self.assertTrue(all(call.kwargs["caption"] == "" for call in bot.copy_message.await_args_list))
        self.assertFalse(hasattr(bot, "forward_message") and bot.forward_message.await_count)

    async def test_unavailable_source_becomes_safe_delivery_error(self):
        bot = AsyncMock()
        bot.copy_message.side_effect = BadRequest("message to copy not found")
        with self.assertRaises(DeliveryError):
            await FileDeliveryService().deliver(bot, 777, record(9))

    async def test_album_can_be_batch_copied_when_captions_are_safe(self):
        bot = AsyncMock()
        result = await FileDeliveryService().deliver(bot, 777, album_record(20, 21, 22))
        self.assertTrue(result.complete)
        bot.copy_messages.assert_awaited_once_with(
            chat_id=777, from_chat_id=-100999, message_ids=(20, 21, 22)
        )
        bot.copy_message.assert_not_awaited()
