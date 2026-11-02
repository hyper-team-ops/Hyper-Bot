"""Authorized administrative messaging and file registry commands."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import Settings
from bot.database.repository import DuplicateFileError, FileNotFoundError, SQLiteFileRepository
from bot.handlers.flows import SEND_FINISH, SEND_MESSAGE
from bot.middleware.authorization import is_admin, reject_unauthorized
from bot.services.deep_links import build_deep_link
from bot.services.file_registry import FileRegistry

logger = logging.getLogger(__name__)


def _parse_message_ids(raw: str) -> tuple[int, ...]:
    try:
        return tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("Message IDs must be comma-separated integers") from exc


def create_admin_handlers(settings: Settings, repository: SQLiteFileRepository,
                          registry: FileRegistry) -> dict[str, object]:
    async def authorize(update: Update) -> bool:
        if is_admin(update, settings.admin_user_ids):
            return True
        await reject_unauthorized(update)
        return False

    async def register_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "الاستخدام: /file_register website_id message_id[,message_id] عنوان الملف [--keep-captions]"
            )
            return
        website_id, raw_ids = context.args[:2]
        title_parts = list(context.args[2:])
        keep_captions = "--keep-captions" in title_parts
        title_parts = [part for part in title_parts if part != "--keep-captions"]
        title = " ".join(title_parts)
        try:
            record = registry.register(
                website_id, title, _parse_message_ids(raw_ids), strip_captions=not keep_captions
            )
        except (ValueError, DuplicateFileError) as exc:
            await update.effective_message.reply_text(f"تعذر التسجيل: {exc}")
            return
        await update.effective_message.reply_text(
            f"✅ تم تسجيل {record.website_id}\n{build_deep_link(settings.bot_username, record.public_token)}"
        )

    async def file_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("الاستخدام: /file_link website_id")
            return
        record = repository.get_by_website_id(context.args[0])
        if record is None:
            await update.effective_message.reply_text("لم يتم العثور على الملف.")
            return
        status = "مفعّل" if record.active else "معطّل"
        await update.effective_message.reply_text(
            f"{record.title} — {status}\n{build_deep_link(settings.bot_username, record.public_token)}"
        )

    async def update_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) != 2:
            await update.effective_message.reply_text("الاستخدام: /file_update website_id message_id[,message_id]")
            return
        try:
            registry.replace_messages(context.args[0], _parse_message_ids(context.args[1]))
        except (ValueError, FileNotFoundError) as exc:
            await update.effective_message.reply_text(f"تعذر التحديث: {exc}")
            return
        await update.effective_message.reply_text("✅ تم تحديث رسائل الملف مع بقاء الرابط نفسه.")

    async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE, active: bool) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("يجب تحديد website_id واحد.")
            return
        try:
            repository.set_active(context.args[0], active)
        except FileNotFoundError:
            await update.effective_message.reply_text("لم يتم العثور على الملف.")
            return
        await update.effective_message.reply_text("✅ تم تفعيل الملف." if active else "✅ تم تعطيل الملف.")

    async def disable_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await set_status(update, context, False)

    async def enable_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await set_status(update, context, True)

    async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("الاستخدام: /file_delete website_id")
            return
        try:
            repository.delete(context.args[0])
        except FileNotFoundError:
            await update.effective_message.reply_text("لم يتم العثور على الملف.")
            return
        await update.effective_message.reply_text("✅ تم حذف الربط نهائياً.")

    async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        query = " ".join(context.args) if context.args else None
        records = repository.list(query)[:30]
        if not records:
            await update.effective_message.reply_text("لا توجد ملفات مطابقة.")
            return
        lines = [f"{'✅' if item.active else '⛔'} {item.website_id} — {item.title}" for item in records]
        await update.effective_message.reply_text("\n".join(lines))

    async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        if not await authorize(update):
            return ConversationHandler.END
        await query.answer()
        if query.data == "admin:finish":
            await query.edit_message_text("أرسل رقم المحادثة ثم اسم الطلب في رسالة واحدة. استخدم /cancel للإلغاء.")
            return SEND_FINISH
        await query.edit_message_text("أرسل رقم المحادثة ثم نص الرسالة في رسالة واحدة. استخدم /cancel للإلغاء.")
        return SEND_MESSAGE

    async def send_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, *, finished: bool) -> int:
        if not await authorize(update) or update.effective_message is None:
            return ConversationHandler.END
        text = update.effective_message.text or ""
        target, separator, body = text.partition(" ")
        try:
            chat_id = int(target)
        except ValueError:
            separator = ""
        if not separator or not body.strip():
            await update.effective_message.reply_text("صيغة غير صحيحة. أرسل رقم المحادثة ثم النص.")
            return ConversationHandler.END
        outgoing = f"تم الانتهاء من تحميل طلبكم!\nاسم الطلب: {body.strip()}" if finished else body.strip()
        try:
            await context.bot.send_message(chat_id, outgoing)
        except TelegramError:
            logger.exception("Admin message delivery failed")
            await update.effective_message.reply_text("تعذر إرسال الرسالة. تحقق من رقم المحادثة.")
            return ConversationHandler.END
        await update.effective_message.reply_text("✅ تم إرسال الرسالة.")
        return ConversationHandler.END

    async def send_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await send_to_user(update, context, finished=True)

    async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await send_to_user(update, context, finished=False)

    return {
        "register": register_file, "link": file_link, "update": update_file,
        "disable": disable_file, "enable": enable_file, "delete": delete_file,
        "list": list_files, "button": admin_button, "finish": send_finish,
        "message": send_message,
    }
