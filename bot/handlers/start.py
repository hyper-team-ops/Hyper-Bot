"""Start, help, cancellation, and deep-link delivery handlers."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.flows import ADMIN_BUTTONS, SEND_REQUEST
from bot.keyboards.keyboards import admin_menu, main_menu
from bot.middleware.authorization import is_admin
from bot.services.deep_links import is_valid_token
from bot.services.file_delivery import DeliveryError, FileDeliveryService
from bot.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

WELCOME = """🎉 أهلاً بك في 'هايبر بوت' مساعدك الذكي من فريق هايبر.

البوت الرسمي لفريق هايبر في كلية الهندسة المعلوماتية، وهنا لتوفير وقتك وجهدك.

اختر الخدمة التي تحتاجها الآن:

• 🔍 استعلامات: للاستعلام عن توفّر كورس أو برنامج لدى مكتب الفريق.
• 📥 طلب تحميل: لإرسال طلب تحميل في حال عدم توفر كورس أو برنامج لدى مكتب الفريق.
• 💡 حول الفريق: لمعرفة المزيد عن خدماتنا الأساسية.
• 💬 شكوى أو اقتراح: لإرسال شكوى أو اقتراح للفريق بصفة مجهولة."""


def create_start_handler(settings: Settings, repository: SQLiteFileRepository,
                         delivery: FileDeliveryService, limiter: RateLimiter):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = update.effective_message
        if message is None:
            return ConversationHandler.END

        # Only this user's state is reset. Shared group chat_data is deliberately untouched.
        context.user_data.clear()
        payload = context.args[0] if context.args else None
        if payload is not None:
            if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
                await message.reply_text(
                    "🔒 إرسال الملفات متاح فقط في المحادثة الخاصة مع البوت."
                )
                return ConversationHandler.END
            if payload == "request":
                await message.reply_text(
                    "فضلاً، أرسل اسم الكورس أو البرنامج وحدد نوعه، وأرفق الرابط "
                    "إن توفر. استخدم /cancel للإلغاء."
                )
                return SEND_REQUEST
            if not is_valid_token(payload):
                await message.reply_text(
                    "❌ عذراً، الملف المطلوب غير متوفر حالياً.",
                    reply_markup=main_menu(),
                )
                return ConversationHandler.END
            user = update.effective_user
            if user is None or not limiter.allow(user.id):
                await message.reply_text("⏳ طلبات كثيرة خلال وقت قصير. يرجى المحاولة بعد قليل.")
                return ConversationHandler.END
            record = repository.get_by_token(payload)
            if record is None or not record.active:
                await message.reply_text(
                    "❌ عذراً، الملف المطلوب غير متوفر حالياً.",
                    reply_markup=main_menu(),
                )
                return ConversationHandler.END
            try:
                result = await delivery.deliver(context.bot, message.chat_id, record)
            except DeliveryError as exc:
                if exc.delivered:
                    await message.reply_text(
                        "⚠️ تم إرسال جزء من الملف فقط. يرجى المحاولة لاحقاً لإكماله.",
                        reply_markup=main_menu(),
                    )
                else:
                    await message.reply_text(
                        "⚠️ تعذر إرسال الملف حالياً. يرجى المحاولة لاحقاً.",
                        reply_markup=main_menu(),
                    )
                return ConversationHandler.END
            if not result.complete:
                await message.reply_text(
                    "⚠️ تم إرسال جزء من الملف فقط. يرجى المحاولة لاحقاً لإكماله.",
                    reply_markup=main_menu(),
                )
                return ConversationHandler.END
            await message.reply_text(
                f"📥 تم إرسال الملف الذي طلبته: {record.title}",
                reply_markup=main_menu(),
            )
            return ConversationHandler.END

        if is_admin(update, settings.admin_user_ids):
            await message.reply_text(
                "أهلاً بالهايبر! قم باختيار أمر من الأسفل.",
                reply_markup=admin_menu(),
            )
            return ADMIN_BUTTONS
        if (
            update.effective_chat is None
            or update.effective_chat.type != ChatType.PRIVATE
        ):
            await message.reply_text(
                "يرجى فتح محادثة خاصة مع البوت لاستخدام خدماته."
            )
            return ConversationHandler.END
        await message.reply_text(WELCOME, reply_markup=main_menu())
        return ConversationHandler.END

    return start


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "بعد إرسال الأمر /start تظهر قائمة الخدمات. اختر خدمة واتبع التعليمات، "
            "أو استخدم /cancel للإلغاء."
        )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.effective_message:
        await update.effective_message.reply_text(
            "تم الإلغاء. يمكنك بدء محادثة جديدة مع البوت الآن.",
            reply_markup=main_menu(),
        )
    return ConversationHandler.END
