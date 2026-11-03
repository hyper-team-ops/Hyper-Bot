"""Secure Telegram administrator review queue."""

from __future__ import annotations

import asyncio
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.middleware.authorization import is_admin, reject_unauthorized
from bot.services.deep_links import build_deep_link
from bot.services.review import ReviewService


def _keyboard(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve Match", callback_data=f"review:a:{candidate_id}"),
         InlineKeyboardButton("❌ Reject Match", callback_data=f"review:r:{candidate_id}")],
        [InlineKeyboardButton("🙈 Ignore File", callback_data=f"review:i:{candidate_id}"),
         InlineKeyboardButton("🔎 Search/Choose", callback_data=f"review:s:{candidate_id}")],
        [InlineKeyboardButton("ℹ️ Show Details", callback_data=f"review:d:{candidate_id}")],
    ])


def _render(repository: SQLiteFileRepository, candidate_id: int, details: bool = False) -> str:
    candidate = repository.get_candidate(candidate_id)
    if candidate is None:
        return "Review item no longer exists."
    item = repository.get_discovered(candidate.discovered_message_id)
    if item is None:
        return "Source discovery no longer exists."
    lines = ["📁 New file discovered", "", f"Filename: {escape(item.filename or 'unknown')}",
             f"Topic: {escape(item.topic_title or str(item.topic_id or 'General'))}",
             f"Size: {item.file_size if item.file_size is not None else 'unknown'} bytes", "",
             "Possible website match:", escape(candidate.website_title or "No reliable match"), "",
             f"Status: {escape(candidate.status)}"]
    if details:
        lines.extend([f"MIME: {escape(item.mime_type or 'unknown')}",
                      f"Confidence: {candidate.confidence:.0%}",
                      f"Reason: {escape(candidate.reason or '-')}",
                      f"Candidate ID: {candidate.id}"])
    return "\n".join(lines)


def create_review_handlers(settings: Settings, repository: SQLiteFileRepository,
                           service: ReviewService) -> dict[str, object]:
    async def authorize(update: Update) -> bool:
        if is_admin(update, settings.admin_user_ids):
            return True
        await reject_unauthorized(update)
        return False

    async def list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        topic_id = None
        if context.args and context.args[0].isdigit():
            topic_id = int(context.args[0])
        candidates = repository.list_candidates(topic_id=topic_id, limit=10)
        if not candidates:
            await update.effective_message.reply_text("No pending review items.")
            return
        await update.effective_message.reply_text(
            f"{len(candidates)} pending item(s). Use /review_next to open the next one."
        )

    async def next_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        candidates = repository.list_candidates(limit=1)
        if not candidates:
            await update.effective_message.reply_text("No pending review items.")
            return
        candidate = candidates[0]
        await update.effective_message.reply_text(
            _render(repository, candidate.id), reply_markup=_keyboard(candidate.id)
        )

    async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        query = " ".join(context.args).strip()
        candidates = repository.list_candidates(query=query or None, limit=20)
        await update.effective_message.reply_text(
            "\n".join(f"{item.id}: {item.website_title or 'unmatched'} ({item.status})"
                      for item in candidates) or "No matching review items."
        )

    async def show_decided(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        status = "ignored" if not context.args else context.args[0]
        candidates = repository.list_candidates(statuses=(status,), limit=50)
        await update.effective_message.reply_text(
            "\n".join(f"{item.id}: {item.website_title or 'unmatched'}" for item in candidates)
            or f"No {status} items."
        )

    async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (not await authorize(update) or update.effective_message is None
                or update.effective_user is None):
            return
        if not context.args:
            await update.effective_message.reply_text(
                "Usage: /review_approve candidate_id [File-ID] [discovery_id,...]"
            )
            return
        try:
            candidate_id = int(context.args[0])
            file_id = context.args[1] if len(context.args) > 1 else None
            grouped = tuple(int(value) for value in context.args[2].split(",")) if len(context.args) > 2 else None
            result = await asyncio.to_thread(
                service.approve, candidate_id, update.effective_user.id,
                file_id=file_id, discovered_ids=grouped
            )
        except (ValueError, LookupError, RuntimeError) as exc:
            await update.effective_message.reply_text(f"Approval failed: {exc}")
            return
        await update.effective_message.reply_text(
            "✅ Approved\n" + build_deep_link(settings.bot_username,
                                               result.record.public_token)
        )

    async def reconsider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        try:
            service.reconsider(int(context.args[0]))
        except (IndexError, ValueError, LookupError) as exc:
            await update.effective_message.reply_text(f"Unable to reconsider: {exc}")
            return
        await update.effective_message.reply_text("Item returned to the review queue.")

    async def batch_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (not await authorize(update) or update.effective_message is None
                or update.effective_user is None):
            return
        try:
            candidate_ids = tuple(int(value) for value in context.args[0].split(","))
        except (IndexError, ValueError):
            await update.effective_message.reply_text(
                "Usage: /review_batch candidate_id,candidate_id"
            )
            return
        approved, failed = 0, []
        for candidate_id in candidate_ids:
            try:
                await asyncio.to_thread(
                    service.approve, candidate_id, update.effective_user.id
                )
                approved += 1
            except (ValueError, LookupError, RuntimeError):
                failed.append(candidate_id)
        await update.effective_message.reply_text(
            f"Batch approved: {approved}. Failed: {','.join(map(str, failed)) or 'none'}."
        )

    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not await authorize(update) or update.effective_user is None:
            return
        await query.answer()
        try:
            _, action, raw_id = (query.data or "").split(":")
            candidate_id = int(raw_id)
            if action == "a":
                result = await asyncio.to_thread(
                    service.approve, candidate_id, update.effective_user.id
                )
                await query.edit_message_text(
                    "✅ Approved\n" + build_deep_link(settings.bot_username,
                                                       result.record.public_token)
                )
            elif action == "r":
                service.reject(candidate_id, update.effective_user.id)
                await query.edit_message_text("❌ Match rejected and retained in history.")
            elif action == "i":
                service.ignore(candidate_id, update.effective_user.id)
                await query.edit_message_text("🙈 File ignored; future scans will not repeat it.")
            elif action == "s":
                await query.edit_message_text(
                    _render(repository, candidate_id, True) +
                    f"\n\nChoose with: /review_approve {candidate_id} File-ID"
                )
            elif action == "d":
                await query.edit_message_text(_render(repository, candidate_id, True),
                                              reply_markup=_keyboard(candidate_id))
        except (ValueError, LookupError, RuntimeError) as exc:
            await query.edit_message_text(f"Review action failed safely: {exc}")

    return {"list": list_pending, "next": next_pending, "search": search,
            "decided": show_decided, "approve": approve_command,
            "batch": batch_approve, "reconsider": reconsider, "callback": callback}
