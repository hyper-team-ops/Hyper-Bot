"""Copy registered Telegram messages to users without forwarding attribution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

from bot.database.models import FileRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: int
    total: int

    @property
    def complete(self) -> bool:
        return self.delivered == self.total


class DeliveryError(RuntimeError):
    def __init__(self, message: str, delivered: int = 0) -> None:
        super().__init__(message)
        self.delivered = delivered


class FileDeliveryService:
    def __init__(self, *, max_retry_after: int = 30) -> None:
        self.max_retry_after = max_retry_after

    async def deliver(self, bot: Bot, chat_id: int, record: FileRecord) -> DeliveryResult:
        if len(record.message_ids) > 1 and not record.strip_captions:
            try:
                await self._copy_many_with_retry(
                    bot,
                    {
                        "chat_id": chat_id,
                        "from_chat_id": record.source_channel_id,
                        "message_ids": record.message_ids,
                    },
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning("Telegram refused registered album copy: %s", type(exc).__name__)
                raise DeliveryError("Source album is unavailable") from exc
            except (NetworkError, TimedOut, TelegramError) as exc:
                logger.warning("Telegram album delivery failed: %s", type(exc).__name__)
                raise DeliveryError("Telegram album delivery failed") from exc
            return DeliveryResult(delivered=len(record.message_ids), total=len(record.message_ids))

        delivered = 0
        for message_id in record.message_ids:
            kwargs: dict[str, object] = {
                "chat_id": chat_id,
                "from_chat_id": record.source_channel_id,
                "message_id": message_id,
            }
            if record.strip_captions:
                kwargs["caption"] = ""
            try:
                await self._copy_with_retry(bot, kwargs)
                delivered += 1
            except (BadRequest, Forbidden) as exc:
                logger.warning("Telegram refused registered message copy: %s", type(exc).__name__)
                raise DeliveryError("Source message is unavailable", delivered) from exc
            except (NetworkError, TimedOut, TelegramError) as exc:
                logger.warning("Telegram file delivery failed: %s", type(exc).__name__)
                raise DeliveryError("Telegram delivery failed", delivered) from exc
        return DeliveryResult(delivered=delivered, total=len(record.message_ids))

    async def _copy_with_retry(self, bot: Bot, kwargs: dict[str, object]) -> None:
        try:
            await bot.copy_message(**kwargs)
        except RetryAfter as exc:
            retry_after = (
                int(exc.retry_after.total_seconds())
                if hasattr(exc.retry_after, "total_seconds")
                else int(exc.retry_after)
            )
            if retry_after > self.max_retry_after:
                raise
            await asyncio.sleep(max(1, retry_after))
            await bot.copy_message(**kwargs)

    async def _copy_many_with_retry(self, bot: Bot, kwargs: dict[str, object]) -> None:
        try:
            await bot.copy_messages(**kwargs)
        except RetryAfter as exc:
            retry_after = (
                int(exc.retry_after.total_seconds())
                if hasattr(exc.retry_after, "total_seconds")
                else int(exc.retry_after)
            )
            if retry_after > self.max_retry_after:
                raise
            await asyncio.sleep(max(1, retry_after))
            await bot.copy_messages(**kwargs)
