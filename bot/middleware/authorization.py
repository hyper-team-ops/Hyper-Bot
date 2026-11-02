"""Telegram administrator authorization."""

from __future__ import annotations

from collections.abc import Collection

from telegram import Update


def is_admin(update: Update, admin_user_ids: Collection[int]) -> bool:
    user = update.effective_user
    return user is not None and user.id in admin_user_ids


async def reject_unauthorized(update: Update) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text("⛔ هذا الأمر متاح للمشرفين فقط.")
    if update.callback_query is not None:
        await update.callback_query.answer("غير مصرح لك بهذا الإجراء.", show_alert=True)
