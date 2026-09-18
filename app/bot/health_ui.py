from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from app.bot.auth import TelegramAuthorizer
from app.diagnostics import ApiHealthReport, ApiHealthResult, ApiHealthService, ApiHealthStatus
from app.runtime import RuntimeContainer

logger = logging.getLogger(__name__)


class TelegramApiHealthController:
    """Read-only inline diagnostics UI for external ASO dependencies."""

    def __init__(self, runtime: RuntimeContainer, authorizer: TelegramAuthorizer) -> None:
        self.runtime = runtime
        self.authorizer = authorizer

    def register(self, application: Application) -> None:
        application.add_handler(CallbackQueryHandler(self.callback, pattern=r"^h\."), group=2)

    async def render_all(self, target: Any) -> None:
        await self._render(target, category=None)

    async def render_core(self, target: Any) -> None:
        await self._render(target, category="core")

    async def render_providers(self, target: Any) -> None:
        await self._render(target, category="provider")

    async def render_nodes(self, target: Any) -> None:
        await self._render(target, category="node")

    async def callback(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = update.effective_user.id if update.effective_user else None
        if query is None or not self.authorizer.is_authorized(user_id):
            if query is not None:
                await query.answer("Access denied.", show_alert=True)
            return
        await query.answer("Running read-only health checks…")
        data = str(query.data or "")
        try:
            if data in {"h.all", "h.refresh"}:
                await self.render_all(query)
            elif data == "h.core":
                await self.render_core(query)
            elif data == "h.providers":
                await self.render_providers(query)
            elif data == "h.nodes":
                await self.render_nodes(query)
            else:
                await query.edit_message_text("Unknown health action.")
        except Exception:
            logger.exception("telegram_api_health_failed")
            await query.edit_message_text(
                "❌ API Health Center failed unexpectedly. No infrastructure mutation was attempted.",
                reply_markup=self._keyboard(),
            )

    async def _render(self, target: Any, *, category: str | None) -> None:
        service = ApiHealthService(self.runtime.database, self.runtime.settings)
        try:
            if category == "core":
                report = ApiHealthReport(results=await service.check_core())
            elif category == "provider":
                report = ApiHealthReport(results=await service.check_providers())
            elif category == "node":
                report = ApiHealthReport(results=await service.check_nodes())
            else:
                report = await service.check_all()
        finally:
            await service.aclose()
        text = self._format_report(report, category=category)
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text, reply_markup=self._keyboard())
        else:
            await target.reply_text(text, reply_markup=self._keyboard())

    @staticmethod
    def _keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 Refresh All", callback_data="h.refresh")],
                [
                    InlineKeyboardButton("🧩 Core APIs", callback_data="h.core"),
                    InlineKeyboardButton("☁️ Providers", callback_data="h.providers"),
                ],
                [InlineKeyboardButton("🖥 Node APIs", callback_data="h.nodes")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="m.status")],
            ]
        )

    @classmethod
    def _format_report(cls, report: ApiHealthReport, *, category: str | None) -> str:
        title = {
            None: "❤️ API Health Center",
            "core": "🧩 Core API Health",
            "provider": "☁️ Provider API Health",
            "node": "🖥 Node API Health",
        }[category]
        lines = [title, ""]
        for item in report.results:
            lines.append(cls._format_result(item))
        lines.extend(
            [
                "",
                f"Healthy: {report.healthy_count} | Failed: {report.failed_count} | "
                f"Degraded: {report.degraded_count}",
                "Read-only diagnostics only; no VPS/Master mutation is performed.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _format_result(item: ApiHealthResult) -> str:
        icon = {
            ApiHealthStatus.HEALTHY: "✅",
            ApiHealthStatus.DEGRADED: "⚠️",
            ApiHealthStatus.FAILED: "❌",
            ApiHealthStatus.NOT_CONFIGURED: "⚪️",
        }[item.status]
        latency = f" · {item.latency_ms}ms" if item.latency_ms is not None else ""
        return f"{icon} {item.label}{latency}\n   {item.detail}"
