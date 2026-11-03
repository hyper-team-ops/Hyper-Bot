"""Authorized administrative messaging and file registry commands."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from telegram import MessageOriginChannel, MessageOriginChat, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import Settings
from bot.database.repository import DuplicateFileError, FileNotFoundError, SQLiteFileRepository
from bot.database.models import FileRecord
from bot.handlers.flows import SEND_FINISH, SEND_MESSAGE
from bot.middleware.authorization import is_admin, reject_unauthorized
from bot.services.deep_links import build_deep_link, validate_website_id
from bot.services.file_delivery import DeliveryError, FileDeliveryService
from bot.services.file_registry import FileRegistry, validate_message_ids
from bot.services.registration_drafts import RegistrationDraftStore

logger = logging.getLogger(__name__)


def _parse_message_ids(raw: str) -> tuple[int, ...]:
    try:
        return tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("Message IDs must be comma-separated integers") from exc


def create_admin_handlers(
    settings: Settings,
    repository: SQLiteFileRepository,
    registry: FileRegistry,
    delivery: FileDeliveryService,
    drafts: RegistrationDraftStore,
    sync_status: Callable[[FileRecord, str], Awaitable[bool]] | None = None,
) -> dict[str, object]:
    async def synchronize(record: FileRecord, status: str) -> None:
        if sync_status is not None:
            await sync_status(record, status)
    async def authorize(update: Update) -> bool:
        if is_admin(update, settings.admin_user_ids):
            return True
        await reject_unauthorized(update)
        return False

    async def require_private_chat(update: Update) -> bool:
        if (
            update.effective_chat is not None
            and update.effective_chat.type == ChatType.PRIVATE
        ):
            return True
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "🔒 نفّذ تسجيل الملفات في محادثة خاصة مع البوت."
            )
        return False

    async def verify_source(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message_ids: tuple[int, ...],
        *,
        strip_captions: bool,
    ) -> bool:
        if update.effective_chat is None or update.effective_message is None:
            return False
        try:
            result = await delivery.deliver_messages(
                bot=context.bot,
                chat_id=update.effective_chat.id,
                source_channel_id=settings.source_chat_id,
                message_ids=message_ids,
                strip_captions=strip_captions,
            )
        except DeliveryError as exc:
            partial = (
                f" تم نسخ {exc.delivered} من {len(message_ids)} رسالة فقط."
                if exc.delivered
                else ""
            )
            await update.effective_message.reply_text(
                "⚠️ تعذر التحقق من قابلية نسخ المصدر؛ لم يتم حفظ الربط." + partial
            )
            return False
        if not result.complete:
            await update.effective_message.reply_text(
                "⚠️ لم يكتمل اختبار النسخ؛ لم يتم حفظ الربط."
            )
            return False
        return True

    async def register_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (
            not await authorize(update)
            or not await require_private_chat(update)
            or update.effective_message is None
        ):
            return
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "الاستخدام: /file_register website_id message_id[,message_id] "
                "عنوان الملف [--keep-captions]"
            )
            return
        website_id, raw_ids = context.args[:2]
        title_parts = list(context.args[2:])
        keep_captions = "--keep-captions" in title_parts
        title_parts = [part for part in title_parts if part != "--keep-captions"]
        title = " ".join(title_parts)
        try:
            validate_website_id(website_id)
            if not title or len(title) > 200:
                raise ValueError("Title must contain 1-200 characters")
            message_ids = validate_message_ids(_parse_message_ids(raw_ids))
            if repository.get_by_website_id(website_id) is not None:
                raise DuplicateFileError("Website ID is already registered")
            if not await verify_source(
                update,
                context,
                message_ids,
                strip_captions=not keep_captions,
            ):
                return
            record = registry.register(
                website_id,
                title,
                message_ids,
                strip_captions=not keep_captions,
            )
        except (ValueError, DuplicateFileError) as exc:
            await update.effective_message.reply_text(f"تعذر التسجيل: {exc}")
            return
        await synchronize(record, "available")
        await update.effective_message.reply_text(
            f"✅ تم تسجيل {record.website_id}\n"
            f"{build_deep_link(settings.bot_username, record.public_token)}"
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
            f"{record.title} — {status}\n"
            f"{build_deep_link(settings.bot_username, record.public_token)}"
        )

    async def update_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (
            not await authorize(update)
            or not await require_private_chat(update)
            or update.effective_message is None
        ):
            return
        if len(context.args) != 2:
            await update.effective_message.reply_text(
                "الاستخدام: /file_update website_id message_id[,message_id]"
            )
            return
        try:
            current = repository.get_by_website_id(context.args[0])
            if current is None:
                raise FileNotFoundError(context.args[0])
            message_ids = validate_message_ids(_parse_message_ids(context.args[1]))
            if not await verify_source(
                update,
                context,
                message_ids,
                strip_captions=current.strip_captions,
            ):
                return
            updated = registry.replace_messages(context.args[0], message_ids)
        except (ValueError, FileNotFoundError, DuplicateFileError) as exc:
            await update.effective_message.reply_text(f"تعذر التحديث: {exc}")
            return
        await synchronize(updated, "available" if updated.active else "unavailable")
        await update.effective_message.reply_text("✅ تم تحديث رسائل الملف مع بقاء الرابط نفسه.")

    async def begin_forwarded_registration(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if (
            not await authorize(update)
            or not await require_private_chat(update)
            or update.effective_message is None
            or update.effective_user is None
        ):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text(
                "الاستخدام: /file_begin website_id عنوان الملف [--keep-captions]"
            )
            return
        website_id = context.args[0]
        title_parts = list(context.args[1:])
        keep_captions = "--keep-captions" in title_parts
        title = " ".join(
            part for part in title_parts if part != "--keep-captions"
        )
        if repository.get_by_website_id(website_id) is not None:
            await update.effective_message.reply_text(
                "تعذر البدء: معرّف الموقع مسجل مسبقاً."
            )
            return
        try:
            drafts.begin(
                update.effective_user.id,
                website_id,
                title,
                strip_captions=not keep_captions,
            )
        except ValueError as exc:
            await update.effective_message.reply_text(f"تعذر البدء: {exc}")
            return
        await update.effective_message.reply_text(
            "أعد توجيه الرسالة أو الألبوم من قناة التخزين إلى هذه المحادثة، "
            "ثم أرسل /file_commit. استخدم /file_abort للإلغاء."
        )

    async def capture_forwarded_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if (
            not await authorize(update)
            or update.effective_message is None
            or update.effective_user is None
        ):
            return
        draft = drafts.get(update.effective_user.id)
        if draft is None:
            await update.effective_message.reply_text(
                "ابدأ أولاً بالأمر /file_begin ثم أعد توجيه الملف."
            )
            return
        origin = update.effective_message.forward_origin
        if (
            isinstance(origin, MessageOriginChat)
            and origin.sender_chat.id == settings.source_chat_id
        ):
            await update.effective_message.reply_text(
                "تعرف البوت على مجموعة التخزين، لكن Telegram لا يرسل رقم الرسالة "
                "الأصلية عند إعادة التوجيه من مجموعة. استخدم المستورد التاريخي "
                "أو /file_register مع رقم الرسالة."
            )
            return
        if (
            not isinstance(origin, MessageOriginChannel)
            or origin.chat.id != settings.source_chat_id
        ):
            await update.effective_message.reply_text(
                "هذه الرسالة ليست معاد توجيهها من مجموعة التخزين المعتمدة."
            )
            return
        try:
            added = draft.add_message(origin.message_id)
        except ValueError as exc:
            await update.effective_message.reply_text(f"تعذر إضافة الرسالة: {exc}")
            return
        if added:
            await update.effective_message.reply_text(
                f"تمت إضافة الرسالة. العدد الحالي: {len(draft.message_ids)}."
            )

    async def commit_forwarded_registration(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if (
            not await authorize(update)
            or not await require_private_chat(update)
            or update.effective_message is None
            or update.effective_user is None
        ):
            return
        draft = drafts.get(update.effective_user.id)
        if draft is None:
            await update.effective_message.reply_text("لا يوجد تسجيل قيد الإعداد.")
            return
        try:
            message_ids = validate_message_ids(draft.message_ids)
        except ValueError:
            await update.effective_message.reply_text(
                "أعد توجيه رسالة واحدة على الأقل قبل الحفظ."
            )
            return
        if not await verify_source(
            update,
            context,
            message_ids,
            strip_captions=draft.strip_captions,
        ):
            return
        try:
            record = registry.register(
                draft.website_id,
                draft.title,
                message_ids,
                strip_captions=draft.strip_captions,
            )
        except (ValueError, DuplicateFileError) as exc:
            await update.effective_message.reply_text(f"تعذر التسجيل: {exc}")
            return
        drafts.finish(update.effective_user.id)
        await synchronize(record, "available")
        await update.effective_message.reply_text(
            f"✅ تم التحقق والتسجيل\n"
            f"{build_deep_link(settings.bot_username, record.public_token)}"
        )

    async def abort_forwarded_registration(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        user = update.effective_user
        removed = user is not None and drafts.abort(user.id)
        await update.effective_message.reply_text(
            "تم إلغاء التسجيل المؤقت."
            if removed
            else "لا يوجد تسجيل مؤقت لإلغائه."
        )

    async def set_status(
        update: Update, context: ContextTypes.DEFAULT_TYPE, active: bool
    ) -> None:
        if not await authorize(update) or update.effective_message is None:
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("يجب تحديد website_id واحد.")
            return
        try:
            record = repository.get_by_website_id(context.args[0])
            if record is None:
                raise FileNotFoundError(context.args[0])
            if active:
                if not await require_private_chat(update):
                    return
                if not await verify_source(
                    update,
                    context,
                    record.message_ids,
                    strip_captions=record.strip_captions,
                ):
                    return
            record = repository.set_active(context.args[0], active)
        except FileNotFoundError:
            await update.effective_message.reply_text("لم يتم العثور على الملف.")
            return
        await synchronize(record, "available" if active else "unavailable")
        await update.effective_message.reply_text(
            "✅ تم تفعيل الملف." if active else "✅ تم تعطيل الملف."
        )

    async def test_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (
            not await authorize(update)
            or not await require_private_chat(update)
            or update.effective_message is None
        ):
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("الاستخدام: /file_test website_id")
            return
        record = repository.get_by_website_id(context.args[0])
        if record is None:
            await update.effective_message.reply_text("لم يتم العثور على الملف.")
            return
        if await verify_source(
            update,
            context,
            record.message_ids,
            strip_captions=record.strip_captions,
        ):
            await update.effective_message.reply_text(
                "✅ اكتمل اختبار النسخ ويمكن للبوت الوصول إلى المصدر حالياً."
            )

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
            record = repository.get_by_website_id(context.args[0])
            if record is None:
                raise FileNotFoundError(context.args[0])
            await synchronize(record, "unavailable")
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
        lines = [
            f"{'✅' if item.active else '⛔'} {item.website_id} — {item.title}"
            for item in records
        ]
        await update.effective_message.reply_text("\n".join(lines))

    async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        if not await authorize(update):
            return ConversationHandler.END
        await query.answer()
        if query.data == "admin:finish":
            await query.edit_message_text(
                "أرسل رقم المحادثة ثم اسم الطلب في رسالة واحدة. "
                "استخدم /cancel للإلغاء."
            )
            return SEND_FINISH
        await query.edit_message_text(
            "أرسل رقم المحادثة ثم نص الرسالة في رسالة واحدة. "
            "استخدم /cancel للإلغاء."
        )
        return SEND_MESSAGE

    async def send_to_user(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        finished: bool,
    ) -> int:
        if not await authorize(update) or update.effective_message is None:
            return ConversationHandler.END
        text = update.effective_message.text or ""
        target, separator, body = text.partition(" ")
        try:
            chat_id = int(target)
        except ValueError:
            separator = ""
        if not separator or not body.strip():
            await update.effective_message.reply_text(
                "صيغة غير صحيحة. أرسل رقم المحادثة ثم النص."
            )
            return ConversationHandler.END
        outgoing = (
            f"تم الانتهاء من تحميل طلبكم!\nاسم الطلب: {body.strip()}"
            if finished
            else body.strip()
        )
        try:
            await context.bot.send_message(chat_id, outgoing)
        except TelegramError as exc:
            logger.warning("Admin message delivery failed: %s", type(exc).__name__)
            await update.effective_message.reply_text(
                "تعذر إرسال الرسالة. تحقق من رقم المحادثة."
            )
            return ConversationHandler.END
        await update.effective_message.reply_text("✅ تم إرسال الرسالة.")
        return ConversationHandler.END

    async def send_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await send_to_user(update, context, finished=True)

    async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await send_to_user(update, context, finished=False)

    return {
        "register": register_file,
        "link": file_link,
        "update": update_file,
        "disable": disable_file,
        "enable": enable_file,
        "delete": delete_file,
        "list": list_files,
        "test": test_file,
        "button": admin_button,
        "finish": send_finish,
        "message": send_message,
        "begin": begin_forwarded_registration,
        "capture": capture_forwarded_message,
        "commit": commit_forwarded_registration,
        "abort": abort_forwarded_registration,
    }
