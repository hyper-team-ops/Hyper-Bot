"""Handle only new media updates arriving from the configured storage forum."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.services.discovery import parse_bot_message
from bot.services.pipeline import DiscoveryPipeline
from bot.services.review import ReviewService

logger = logging.getLogger(__name__)


def create_storage_handler(settings: Settings, pipeline: DiscoveryPipeline,
                           review: ReviewService):
    async def storage_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or chat.id != settings.source_chat_id:
            return
        result = pipeline.process(parse_bot_message(message, settings.source_chat_id))
        if result.duplicate or not result.accepted or result.match is None:
            return
        discovered = pipeline.repository.get_discovered_message(
            settings.source_chat_id, result.metadata.message_id
        )
        pending = pipeline.repository.list_candidates(
            statuses=(result.match.status.value,), limit=100
        )
        candidate = next((value for value in pending
                          if discovered is not None and
                          value.discovered_message_id == discovered.id), None)
        if candidate is not None:
            await asyncio.to_thread(review.mark_pending, candidate.id)
        # An album is allowed to settle in the review queue. Registering its first
        # update immediately would create a partial public resource.
        if (settings.auto_approve_exact_matches
                and result.match.status.value == "exact"
                and result.metadata.media_group_id is None):
            if candidate is not None:
                try:
                    await asyncio.to_thread(review.approve, candidate.id, 0)
                except Exception as exc:
                    logger.warning("Automatic live registration failed: %s",
                                   type(exc).__name__)
    return storage_message
