"""Application composition and polling entry point."""

from __future__ import annotations

import logging
import re
import warnings

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import ConfigurationError, Settings
from bot.database.repository import SQLiteFileRepository
from bot.handlers.admin import create_admin_handlers
from bot.handlers.flows import (
    ADMIN_BUTTONS,
    COMPLAINT_STATE,
    SEND_FINISH,
    SEND_MESSAGE,
    SEND_REQUEST,
    create_complaint_handler,
    create_menu_handler,
    create_request_handler,
)
from bot.handlers.start import cancel_command, create_start_handler, help_command
from bot.keyboards.keyboards import (
    CHECK_AVAILABILITY,
    COMPLAINT,
    DOWNLOAD_REQUEST,
    TEAM_INFO,
)
from bot.services.file_delivery import FileDeliveryService
from bot.services.file_registry import FileRegistry
from bot.services.rate_limit import RateLimiter
from bot.services.registration_drafts import RegistrationDraftStore
from bot.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def build_application(settings: Settings) -> Application:
    repository = SQLiteFileRepository(settings.database_path)
    registry = FileRegistry(repository, settings.source_channel_id)
    delivery = FileDeliveryService()
    limiter = RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
    drafts = RegistrationDraftStore()
    start = create_start_handler(settings, repository, delivery, limiter)
    menu = create_menu_handler(settings)
    request = create_request_handler(settings)
    complaint = create_complaint_handler(settings)
    admin = create_admin_handlers(
        settings, repository, registry, delivery, drafts
    )

    application = Application.builder().token(settings.bot_token).build()

    # Management commands remain available even while an unrelated conversation is open.
    application.add_handler(CommandHandler("file_register", admin["register"]), group=0)
    application.add_handler(CommandHandler("file_link", admin["link"]), group=0)
    application.add_handler(CommandHandler("file_update", admin["update"]), group=0)
    application.add_handler(CommandHandler("file_disable", admin["disable"]), group=0)
    application.add_handler(CommandHandler("file_enable", admin["enable"]), group=0)
    application.add_handler(CommandHandler("file_delete", admin["delete"]), group=0)
    application.add_handler(CommandHandler("file_test", admin["test"]), group=0)
    application.add_handler(CommandHandler("files", admin["list"]), group=0)
    application.add_handler(CommandHandler("file_begin", admin["begin"]), group=0)
    application.add_handler(CommandHandler("file_commit", admin["commit"]), group=0)
    application.add_handler(CommandHandler("file_abort", admin["abort"]), group=0)

    menu_pattern = "^(?:" + "|".join(
        re.escape(choice)
        for choice in (CHECK_AVAILABILITY, DOWNLOAD_REQUEST, TEAM_INFO, COMPLAINT)
    ) + ")$"
    private_menu_choice = filters.ChatType.PRIVATE & filters.Regex(menu_pattern)

    # Captures only authorized administrators' forwarded storage messages and prevents
    # them from falling through into an unrelated active user conversation.
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.User(user_id=settings.admin_user_ids)
            & filters.FORWARDED,
            admin["capture"],
        ),
        group=1,
    )

    # The admin callback and its following text must share a per-user/per-chat key, not
    # a per-message key. PTB warns about this intentional mixed callback/text design.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="If 'per_message=False'.*",
            category=PTBUserWarning,
        )
        conversation = ConversationHandler(
            entry_points=[
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel_command),
                MessageHandler(private_menu_choice, menu),
            ],
            states={
                ADMIN_BUTTONS: [
                    CallbackQueryHandler(
                        admin["button"], pattern=r"^admin:(finish|message)$"
                    )
                ],
                SEND_FINISH: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin["finish"]
                    )
                ],
                SEND_MESSAGE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, admin["message"]
                    )
                ],
                SEND_REQUEST: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, request)
                ],
                COMPLAINT_STATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint)
                ],
            },
            fallbacks=[
                CommandHandler("start", start),
                CommandHandler("help", help_command),
                CommandHandler("cancel", cancel_command),
            ],
            # Active states receive all text, even if it equals a menu button.
            allow_reentry=False,
        )
    application.add_handler(conversation, group=1)
    # This is deliberately in the same group and after ConversationHandler. It handles
    # unknown private-chat text only when no active state consumed the update.
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, menu),
        group=1,
    )

    async def error_handler(update: object, context: object) -> None:
        error = getattr(context, "error", None)
        if isinstance(error, (NetworkError, TimedOut)):
            logger.warning("Transient Telegram network error: %s", type(error).__name__)
        else:
            error_info = (
                (type(error), error, error.__traceback__)
                if isinstance(error, BaseException)
                else None
            )
            logger.error("Unhandled update error", exc_info=error_info)

    application.add_error_handler(error_handler)
    application.bot_data["settings"] = settings
    application.bot_data["repository"] = repository
    return application


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    configure_logging(settings.log_level)
    logger.info("Starting Hyper Team bot")
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
