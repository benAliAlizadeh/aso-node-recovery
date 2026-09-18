from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.bot.auth import TelegramAuthorizer
from app.bot.callbacks import CallbackSigner, InvalidCallbackData
from app.bot.formatters import (
    format_dashboard,
    format_events,
    format_job_progress,
    format_jobs,
    format_node_detail,
    format_nodes,
    format_providers,
    format_settings,
)
from app.bot.notifier import TelegramEventNotifier
from app.control import ControlService, JobSnapshot
from app.runtime import RuntimeContainer

logger = logging.getLogger(__name__)


class TelegramBotController:
    def __init__(self, runtime: RuntimeContainer) -> None:
        self.runtime = runtime
        self.control: ControlService = runtime.control
        self.settings = runtime.settings
        self.authorizer = TelegramAuthorizer(self.settings.telegram_authorized_user_ids)
        if self.settings.telegram_callback_secret is None:
            raise ValueError("Telegram callback secret is required")
        self.signer = CallbackSigner(self.settings.telegram_callback_secret)

    def register(self, application: Application) -> None:
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("status", self.status),
            CommandHandler("nodes", self.nodes),
            CommandHandler("node", self.node),
            CommandHandler("check", self.check),
            CommandHandler("replace", self.replace),
            CommandHandler("jobs", self.jobs),
            CommandHandler("logs", self.logs),
            CommandHandler("settings", self.settings_command),
            CommandHandler("providers", self.providers),
            CommandHandler("pause", self.pause),
            CommandHandler("resume", self.resume),
            CallbackQueryHandler(self.callback, pattern=r"^(ck|rp|rc|ju|jr|ja|jc|pt|pe|pd)\."),
        ]
        application.add_handlers(handlers)

    async def _authorized(self, update: Update) -> tuple[bool, int | None]:
        user_id = update.effective_user.id if update.effective_user else None
        if self.authorizer.is_authorized(user_id):
            return True, user_id
        if update.callback_query:
            await update.callback_query.answer("Access denied.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("Access denied.")
        logger.warning("telegram_access_denied", extra={"telegram_user_id": user_id})
        return False, user_id

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if not ok or not update.effective_message:
            return
        await update.effective_message.reply_text(
            "ASO Node Recovery\n\n"
            "/status /nodes /node <id|name> /check <id|name>\n"
            "/replace <id|name> /jobs /logs /providers /settings\n"
            "/pause /resume"
        )

    async def status(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if ok and update.effective_message:
            await update.effective_message.reply_text(
                format_dashboard(await self.control.dashboard())
            )

    async def nodes(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if not ok or not update.effective_message:
            return
        nodes = await self.control.list_nodes(limit=50)
        keyboard = [
            [InlineKeyboardButton(node.name, callback_data=f"ck.{node.id.hex}")]
            for node in nodes[:20]
        ]
        await update.effective_message.reply_text(
            format_nodes(nodes),
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )

    async def node(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if not ok or not update.effective_message:
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /node <uuid|name>")
            return
        detail = await self.control.resolve_node(" ".join(context.args))
        if detail is None:
            await update.effective_message.reply_text("Node not found.")
            return
        node_id = detail.node.id
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("Check", callback_data=f"ck.{node_id.hex}"),
                InlineKeyboardButton("Replace", callback_data=f"rp.{node_id.hex}"),
            ]]
        )
        await update.effective_message.reply_text(format_node_detail(detail), reply_markup=keyboard)

    async def check(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if not ok or user_id is None or not update.effective_message:
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /check <uuid|name>")
            return
        detail = await self.control.resolve_node(" ".join(context.args))
        if detail is None:
            await update.effective_message.reply_text("Node not found.")
            return
        result = await self.control.manual_check(detail.node.id, actor_user_id=user_id)
        refreshed = await self.control.resolve_node(str(detail.node.id))
        text = f"Manual check result: {result}"
        if refreshed is not None:
            text += "\n\n" + format_node_detail(refreshed)
        await update.effective_message.reply_text(text)

    async def replace(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if not ok or user_id is None or not update.effective_message:
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /replace <uuid|name>")
            return
        detail = await self.control.resolve_node(" ".join(context.args))
        if detail is None:
            await update.effective_message.reply_text("Node not found.")
            return
        await self._send_replace_confirmation(update.effective_message, detail.node.id, user_id)

    async def jobs(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if not ok or not update.effective_message:
            return
        jobs = await self.control.list_jobs(limit=20)
        keyboard = []
        for job in jobs[:10]:
            if job.active:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"Resume {str(job.id)[:8]}", callback_data=f"ju.{job.id.hex}"
                        ),
                        InlineKeyboardButton(
                            f"Cancel {str(job.id)[:8]}", callback_data=f"ja.{job.id.hex}"
                        ),
                    ]
                )
        await update.effective_message.reply_text(
            format_jobs(jobs),
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )

    async def logs(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if ok and update.effective_message:
            await update.effective_message.reply_text(
                format_events(await self.control.list_events(limit=15))
            )

    async def settings_command(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if ok and update.effective_message:
            await update.effective_message.reply_text(
                format_settings(await self.control.settings_snapshot())
            )

    async def providers(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, _ = await self._authorized(update)
        if not ok or not update.effective_message:
            return
        providers = await self.control.list_providers()
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'Disable' if provider.is_active else 'Enable'} {provider.key}",
                    callback_data=f"pt.{provider.id.hex}",
                )
            ]
            for provider in providers
        ]
        await update.effective_message.reply_text(
            format_providers(providers),
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )

    async def pause(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if ok and user_id is not None and update.effective_message:
            changed = await self.control.set_paused(True, actor_user_id=user_id)
            await update.effective_message.reply_text(
                "System paused." if changed else "System was already paused."
            )

    async def resume(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if ok and user_id is not None and update.effective_message:
            changed = await self.control.set_paused(False, actor_user_id=user_id)
            await update.effective_message.reply_text(
                "System resumed." if changed else "System was already running."
            )

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        query = update.callback_query
        if not ok or user_id is None or query is None or not isinstance(query.data, str):
            return
        await query.answer()
        try:
            action, raw_id = query.data.split(".", 1)
            if action in {"rc", "jr", "jc", "pe", "pd"}:
                verified = self.signer.verify(query.data, user_id)
                entity_id = verified.entity_id
            else:
                entity_id = UUID(hex=raw_id)
        except (ValueError, InvalidCallbackData):
            await query.edit_message_text("This action is invalid or expired.")
            return

        if action == "ck":
            result = await self.control.manual_check(entity_id, actor_user_id=user_id)
            detail = await self.control.resolve_node(str(entity_id))
            text = f"Manual check result: {result}"
            if detail is not None:
                text += "\n\n" + format_node_detail(detail)
            await query.edit_message_text(text)
            return

        if action == "rp":
            await self._edit_replace_confirmation(query, entity_id, user_id)
            return
        if action == "rc":
            job_id = await self.control.trigger_replacement(entity_id, actor_user_id=user_id)
            await query.edit_message_text("Replacement accepted. Starting workflow…")
            context.application.create_task(
                self._run_job_progress(context.application, query.message.chat_id, job_id, user_id)
            )
            return

        if action == "ju":
            signed = self.signer.encode("jr", entity_id, user_id)
            await query.edit_message_text(
                "Resume this replacement job?",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Confirm resume", callback_data=signed)]]
                ),
            )
            return
        if action == "jr":
            await query.edit_message_text("Resume accepted.")
            context.application.create_task(
                self._run_job_progress(
                    context.application,
                    query.message.chat_id,
                    entity_id,
                    user_id,
                )
            )
            return

        if action == "ja":
            signed = self.signer.encode("jc", entity_id, user_id)
            await query.edit_message_text(
                "Cancel this replacement job? Cancellation is refused after Master switch.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Confirm cancel", callback_data=signed)]]
                ),
            )
            return
        if action == "jc":
            await self.control.cancel_job(entity_id, actor_user_id=user_id)
            await query.edit_message_text("Replacement job cancelled.")
            return

        if action == "pt":
            providers = {provider.id: provider for provider in await self.control.list_providers()}
            provider = providers.get(entity_id)
            if provider is None:
                await query.edit_message_text("Provider not found.")
                return
            next_action = "pd" if provider.is_active else "pe"
            signed = self.signer.encode(next_action, entity_id, user_id)
            verb = "disable" if provider.is_active else "enable"
            await query.edit_message_text(
                f"Confirm {verb} provider {provider.display_name}?",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f"Confirm {verb}", callback_data=signed)]]
                ),
            )
            return

        if action in {"pe", "pd"}:
            active = action == "pe"
            await self.control.set_provider_active(entity_id, active, actor_user_id=user_id)
            await query.edit_message_text(f"Provider {'enabled' if active else 'disabled'}.")
            return

    async def _send_replace_confirmation(
        self,
        message: object,
        node_id: UUID,
        user_id: int,
    ) -> None:
        signed = self.signer.encode("rc", node_id, user_id)
        await message.reply_text(
            "Replace this node? The old VPS is protected until all verification gates pass.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Confirm replacement", callback_data=signed)]]
            ),
        )

    async def _edit_replace_confirmation(self, query: object, node_id: UUID, user_id: int) -> None:
        signed = self.signer.encode("rc", node_id, user_id)
        await query.edit_message_text(
            "Replace this node? The old VPS is protected until all verification gates pass.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Confirm replacement", callback_data=signed)]]
            ),
        )

    async def _run_job_progress(
        self,
        application: Application,
        chat_id: int,
        job_id: UUID,
        actor_user_id: int,
    ) -> None:
        message = await application.bot.send_message(chat_id=chat_id, text="Loading replacement…")
        workflow = asyncio.create_task(
            self.control.resume_job(job_id, actor_user_id=actor_user_id)
        )
        last_text = ""
        try:
            while not workflow.done():
                job = await self.control.get_job(job_id)
                if job is not None:
                    text = format_job_progress(job)
                    if text != last_text:
                        await self._safe_edit(message, text)
                        last_text = text
                await asyncio.sleep(self.settings.telegram_progress_interval_seconds)
            await workflow
        except Exception as exc:
            logger.exception("telegram_manual_replacement_failed", extra={"job_id": str(job_id)})
            await self._safe_edit(message, f"Replacement workflow error: {exc}")
            return

        job = await self.control.get_job(job_id)
        if job is not None:
            await self._safe_edit(message, format_job_progress(job))

    @staticmethod
    async def _safe_edit(message: object, text: str) -> None:
        try:
            await message.edit_text(text)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise


def build_telegram_application(runtime: RuntimeContainer) -> Application:
    settings = runtime.settings
    if not settings.telegram_bot_enabled:
        raise ValueError("ASO_TELEGRAM_BOT_ENABLED must be true to start Telegram")
    if settings.telegram_bot_token is None:
        raise ValueError("ASO_TELEGRAM_BOT_TOKEN is required")

    controller = TelegramBotController(runtime)
    notifier = (
        TelegramEventNotifier(
            runtime.control,
            chat_id=settings.telegram_notification_chat_id,
        )
        if settings.telegram_notification_chat_id is not None
        else None
    )

    async def post_init(application: Application) -> None:
        if notifier is not None:
            if application.job_queue is None:
                raise RuntimeError("python-telegram-bot JobQueue extra is required")
            async def notify(context: ContextTypes.DEFAULT_TYPE) -> None:
                try:
                    await notifier.run_once(context.bot)
                except Exception:
                    logger.exception("telegram_event_notifier_failed")
            application.job_queue.run_repeating(
                notify,
                interval=settings.telegram_notification_interval_seconds,
                first=1.0,
                name="aso-event-notifier",
            )

    async def post_shutdown(_: Application) -> None:
        await runtime.close()

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token.get_secret_value())
        .concurrent_updates(False)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    controller.register(application)
    return application
