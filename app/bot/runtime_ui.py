from __future__ import annotations

from typing import Any
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.bot.auth import TelegramAuthorizer
from app.bot.callbacks import CallbackSigner, InvalidCallbackData
from app.models import NodeOperationMode, RuntimeExecutionMode
from app.runtime import RuntimeContainer

_GLOBAL_ID = UUID(int=0)


class TelegramRuntimeControlController:
    """Inline runtime controls with hard environment safety boundaries."""

    def __init__(
        self,
        runtime: RuntimeContainer,
        authorizer: TelegramAuthorizer,
        signer: CallbackSigner,
    ) -> None:
        self.runtime = runtime
        self.control = runtime.control
        self.authorizer = authorizer
        self.signer = signer

    def register(self, application: Application) -> None:
        application.add_handler(CommandHandler("controls", self.controls), group=2)
        application.add_handler(CallbackQueryHandler(self.callback, pattern=r"^o\."), group=2)
        application.add_handler(
            CallbackQueryHandler(
                self.signed_callback,
                pattern=r"^(me|md|ae|ad|xl|xd|na|nm|nd)\.",
            ),
            group=2,
        )

    async def controls(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if ok and user_id is not None and update.effective_message is not None:
            await self.render_controls(update.effective_message, user_id)

    async def callback(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        query = update.callback_query
        if not ok or user_id is None or query is None or not isinstance(query.data, str):
            return
        await query.answer()
        data = query.data
        if data == "o.controls":
            await self.render_controls(query, user_id)
            return
        if data == "o.live.confirm":
            await query.edit_message_text(
                "⚠️ Enable LIVE execution?\n\n"
                "This only succeeds if server-side safety gates already allow real infrastructure "
                "mutation. Telegram cannot bypass DRY_RUN or Emergency Stop.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Confirm LIVE",
                                callback_data=self.signer.encode("xl", _GLOBAL_ID, user_id),
                            )
                        ],
                        [InlineKeyboardButton("Cancel", callback_data="o.controls")],
                    ]
                ),
            )
            return
        if data == "o.auto.confirm":
            await query.edit_message_text(
                "Enable automatic repair worker?\n\n"
                "Only nodes explicitly set to AUTO REPAIR are eligible. In DRY_RUN it will not "
                "auto-trigger real replacements.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Enable Auto Repair",
                                callback_data=self.signer.encode("ae", _GLOBAL_ID, user_id),
                            )
                        ],
                        [InlineKeyboardButton("Cancel", callback_data="o.controls")],
                    ]
                ),
            )
            return
        if data.startswith("o.n."):
            parts = data.split(".")
            if len(parts) == 3:
                await self.render_node_mode(query, UUID(hex=parts[2]), user_id)
                return
            if len(parts) == 5 and parts[2] == "auto" and parts[3] == "confirm":
                node_id = UUID(hex=parts[4])
                await query.edit_message_text(
                    "Enable AUTO REPAIR for this node?\n\n"
                    "Monitoring failures may automatically start replacement only when global Auto "
                    "Repair is enabled and execution is LIVE-capable.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "✅ Confirm AUTO REPAIR",
                                    callback_data=self.signer.encode("na", node_id, user_id),
                                )
                            ],
                            [InlineKeyboardButton("Cancel", callback_data=f"o.n.{node_id.hex}")],
                        ]
                    ),
                )
                return

    async def signed_callback(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        query = update.callback_query
        if not ok or user_id is None or query is None or not isinstance(query.data, str):
            return
        await query.answer()
        try:
            verified = self.signer.verify(query.data, user_id)
        except InvalidCallbackData:
            await query.edit_message_text("This confirmation is invalid or expired.")
            return

        action = verified.action
        if action == "me":
            await self.control.set_runtime_monitoring(True, actor_user_id=user_id)
            await self.render_controls(query, user_id)
            return
        if action == "md":
            await self.control.set_runtime_monitoring(False, actor_user_id=user_id)
            await self.render_controls(query, user_id)
            return
        if action == "ae":
            await self.control.set_runtime_replacement(True, actor_user_id=user_id)
            await self.render_controls(query, user_id)
            return
        if action == "ad":
            await self.control.set_runtime_replacement(False, actor_user_id=user_id)
            await self.render_controls(query, user_id)
            return
        if action == "xd":
            await self.control.set_runtime_execution_mode(
                RuntimeExecutionMode.DRY_RUN, actor_user_id=user_id
            )
            await self.render_controls(query, user_id)
            return
        if action == "xl":
            try:
                await self.control.set_runtime_execution_mode(
                    RuntimeExecutionMode.LIVE, actor_user_id=user_id
                )
            except Exception as exc:
                await query.edit_message_text(
                    f"LIVE mode refused by safety gates:\n{self._safe_error(exc)}",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⬅️ Controls", callback_data="o.controls")]]
                    ),
                )
                return
            await self.render_controls(query, user_id)
            return

        mode = {
            "nd": NodeOperationMode.DISABLED,
            "nm": NodeOperationMode.MONITOR_ONLY,
            "na": NodeOperationMode.AUTO_REPAIR,
        }.get(action)
        if mode is not None:
            try:
                await self.control.set_node_operation_mode(
                    verified.entity_id, mode, actor_user_id=user_id
                )
            except Exception as exc:
                await query.edit_message_text(
                    f"Node mode change failed:\n{self._safe_error(exc)}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "⬅️ Node Mode",
                                    callback_data=f"o.n.{verified.entity_id.hex}",
                                )
                            ]
                        ]
                    ),
                )
                return
            await self.render_node_mode(query, verified.entity_id, user_id)

    async def render_controls(self, target: Any, user_id: int) -> None:
        snapshot = await self.control.runtime_controls()
        mode = "DRY RUN" if snapshot.effective_dry_run else "LIVE"
        live_note = (
            "available"
            if snapshot.live_capable
            else f"locked: {snapshot.live_block_reason}"
        )
        text = (
            "⚙️ Runtime Controls\n\n"
            f"System: {'PAUSED' if snapshot.paused else 'RUNNING'}\n"
            f"Monitoring: {'ON' if snapshot.monitoring_enabled else 'OFF'}\n"
            f"Auto Repair Worker: {'ON' if snapshot.replacement_enabled else 'OFF'}\n"
            f"Execution: {mode}\n"
            f"LIVE capability: {live_note}\n\n"
            "AUTO REPAIR only applies to nodes explicitly configured for it.\n"
            "Environment safety gates always override Telegram controls."
        )
        monitoring_action = "md" if snapshot.monitoring_enabled else "me"
        auto_action = "ad" if snapshot.replacement_enabled else None
        rows = [
            [
                InlineKeyboardButton(
                    "⏹ Monitoring OFF" if snapshot.monitoring_enabled else "▶️ Monitoring ON",
                    callback_data=self.signer.encode(monitoring_action, _GLOBAL_ID, user_id),
                )
            ],
            [
                InlineKeyboardButton(
                    (
                        "⏹ Auto Repair OFF"
                        if snapshot.replacement_enabled
                        else "▶️ Auto Repair ON"
                    ),
                    callback_data=(
                        self.signer.encode(auto_action, _GLOBAL_ID, user_id)
                        if auto_action
                        else "o.auto.confirm"
                    ),
                )
            ],
        ]
        if snapshot.effective_dry_run:
            rows.append([InlineKeyboardButton("🔴 Request LIVE", callback_data="o.live.confirm")])
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        "🟡 Switch to DRY RUN",
                        callback_data=self.signer.encode("xd", _GLOBAL_ID, user_id),
                    )
                ]
            )
        rows.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="m.status")])
        await self._edit_or_reply(target, text, InlineKeyboardMarkup(rows))

    async def render_node_mode(self, target: Any, node_id: UUID, user_id: int) -> None:
        detail = await self.control.resolve_node(str(node_id))
        if detail is None:
            await self._edit_or_reply(
                target,
                "Node not found.",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Nodes", callback_data="r.nodes")]]
                ),
            )
            return
        mode = detail.node.operation_mode
        text = (
            f"⚙️ {detail.node.name} — Operation Mode\n\n"
            f"Current: {mode.value}\n\n"
            "DISABLED: no scheduled monitoring or auto repair.\n"
            "MONITOR ONLY: Check-Host monitoring only.\n"
            "AUTO REPAIR: monitoring + eligible for automatic replacement when globally enabled."
        )
        rows = [
            [
                InlineKeyboardButton(
                    "⛔ Disabled" + (" ✅" if mode is NodeOperationMode.DISABLED else ""),
                    callback_data=self.signer.encode("nd", node_id, user_id),
                )
            ],
            [
                InlineKeyboardButton(
                    "👁 Monitor Only"
                    + (" ✅" if mode is NodeOperationMode.MONITOR_ONLY else ""),
                    callback_data=self.signer.encode("nm", node_id, user_id),
                )
            ],
            [
                InlineKeyboardButton(
                    "🛠 Auto Repair" + (" ✅" if mode is NodeOperationMode.AUTO_REPAIR else ""),
                    callback_data=(
                        self.signer.encode("na", node_id, user_id)
                        if mode is NodeOperationMode.AUTO_REPAIR
                        else f"o.n.auto.confirm.{node_id.hex}"
                    ),
                )
            ],
            [InlineKeyboardButton("⬅️ Node", callback_data=f"r.n.{node_id.hex}")],
        ]
        await self._edit_or_reply(target, text, InlineKeyboardMarkup(rows))

    async def _authorized(self, update: Update) -> tuple[bool, int | None]:
        user_id = update.effective_user.id if update.effective_user else None
        if self.authorizer.is_authorized(user_id):
            return True, user_id
        if update.callback_query:
            await update.callback_query.answer("Access denied.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("Access denied.")
        return False, user_id

    @staticmethod
    async def _edit_or_reply(target: Any, text: str, markup: InlineKeyboardMarkup) -> None:
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text, reply_markup=markup)
        else:
            await target.reply_text(text, reply_markup=markup)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = " ".join(str(exc).split()) or exc.__class__.__name__
        return text[:500]
