from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from app.bot.auth import TelegramAuthorizer
from app.bot.callbacks import CallbackSigner, InvalidCallbackData
from app.models import ProviderType, SshAuthMethod
from app.registry.management import RegistryManagementService
from app.runtime import RuntimeContainer

logger = logging.getLogger(__name__)
_WIZARD_KEY = "aso_registry_wizard"


class TelegramRegistryController:
    """Inline Telegram registry UX. External mutations remain forbidden in this controller."""

    def __init__(
        self,
        runtime: RuntimeContainer,
        authorizer: TelegramAuthorizer,
        signer: CallbackSigner,
    ) -> None:
        self.runtime = runtime
        self.authorizer = authorizer
        self.signer = signer
        self.service = RegistryManagementService(runtime.database, runtime.settings)

    def register(self, application: Application) -> None:
        application.add_handler(CallbackQueryHandler(self.callback, pattern=r"^r\."), group=1)
        application.add_handler(
            CallbackQueryHandler(self.signed_callback, pattern=r"^(px|nx|pc|nc|sc|hk)\."),
            group=1,
        )
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.message),
            group=1,
        )

    async def render_providers(self, target: Any) -> None:
        providers = await self.service.list_providers()
        rows = [
            [
                InlineKeyboardButton(
                    f"{'🟢' if provider.is_active else '⚪️'} {provider.display_name}",
                    callback_data=f"r.p.{provider.id.hex}",
                )
            ]
            for provider in providers[:30]
        ]
        rows.append([InlineKeyboardButton("➕ Add Provider", callback_data="r.pa")])
        rows.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="m.status")])
        text = "☁️ Providers\n\nSelect a provider to manage it."
        if not providers:
            text += "\nNo providers configured yet."
        await self._edit_or_reply(target, text, InlineKeyboardMarkup(rows))

    async def render_nodes(self, target: Any) -> None:
        nodes = await self.service.list_nodes()
        rows = [
            [
                InlineKeyboardButton(
                    f"🖥 {node.name}",
                    callback_data=f"r.n.{node.id.hex}",
                )
            ]
            for node in nodes[:30]
        ]
        rows.append([InlineKeyboardButton("➕ Add Node", callback_data="r.na")])
        rows.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="m.status")])
        text = "🖥 Nodes\n\nSelect a node to manage it."
        if not nodes:
            text += "\nNo nodes configured yet."
        await self._edit_or_reply(target, text, InlineKeyboardMarkup(rows))

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        query = update.callback_query
        if not ok or user_id is None or query is None or not isinstance(query.data, str):
            return
        await query.answer()
        data = query.data
        try:
            if data == "r.cancel":
                await self._cancel_wizard(context)
                await query.edit_message_text("Cancelled.")
                return
            if data == "r.providers":
                await self.render_providers(query)
                return
            if data == "r.nodes":
                await self.render_nodes(query)
                return
            if data == "r.pa":
                await self._start_provider_add(query, context)
                return
            if data.startswith("r.pat."):
                await self._provider_type_selected(query, context, data.rsplit(".", 1)[1])
                return
            if data == "r.pac":
                await self._commit_provider_add(query, context)
                return
            if data.startswith("r.p."):
                await self._provider_action(query, context, user_id, data)
                return
            if data == "r.na":
                await self._start_node_add(query, context)
                return
            if data.startswith("r.nap."):
                await self._node_provider_selected(query, context, data.rsplit(".", 1)[1])
                return
            if data.startswith("r.naa."):
                await self._node_auth_selected(query, context, data.rsplit(".", 1)[1])
                return
            if data == "r.nac":
                await self._commit_node_add(query, context)
                return
            if data.startswith("r.nsa."):
                await self._node_ssh_edit_auth_selected(query, context, data)
                return
            if data.startswith("r.n."):
                await self._node_action(query, context, user_id, data)
                return
        except Exception as exc:
            logger.exception("telegram_registry_callback_failed")
            await self._safe_edit(query, f"❌ {self._safe_error(exc)}")

    async def signed_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        query = update.callback_query
        if not ok or user_id is None or query is None or not isinstance(query.data, str):
            return
        await query.answer()
        try:
            verified = self.signer.verify(query.data, user_id)
            action = verified.action
            entity_id = verified.entity_id
            wizard = context.user_data.get(_WIZARD_KEY, {})
            if action == "hk":
                if not isinstance(wizard, dict) or wizard.get("stage") != "ssh_host_key_confirm":
                    raise ValueError("SSH host-key confirmation session expired")
                if wizard.get("host_key_confirmation_id") != str(entity_id):
                    raise ValueError("SSH host-key confirmation does not match this session")
                candidate = await self.service.trust_ssh_host_key(
                    host=wizard["ssh_host"],
                    port=int(wizard["ssh_port"]),
                    expected_fingerprint=wizard["ssh_host_key_fingerprint"],
                )
                resume_stage = wizard.pop("host_key_resume_stage")
                wizard["stage"] = resume_stage
                wizard.pop("host_key_confirmation_id", None)
                await query.edit_message_text(
                    "✅ SSH host key trusted.\n"
                    f"{candidate.algorithm} · {candidate.fingerprint}\n\n"
                    + self._ssh_secret_prompt(resume_stage)
                )
                return
            if action == "px":
                await self.service.remove_provider_from_registry(entity_id)
                await query.edit_message_text("Provider removed from ASO registry only. No VPS was touched.")
                return
            if action == "nx":
                await self.service.remove_node_from_registry(entity_id)
                await query.edit_message_text("Node removed from ASO registry only. VPS/Master were not changed.")
                return
            if action == "pc":
                self._require_stage(wizard, "provider_token", entity_id)
                await self.service.replace_provider_token(entity_id, wizard["staged_ref"])
                context.user_data.pop(_WIZARD_KEY, None)
                await query.edit_message_text("✅ Provider API token validated and replaced.")
                return
            if action == "nc":
                self._require_stage(wizard, "node_token", entity_id)
                await self.service.replace_node_api_token(entity_id, wizard["staged_ref"])
                context.user_data.pop(_WIZARD_KEY, None)
                await query.edit_message_text("✅ Node API token validated and replaced.")
                return
            if action == "sc":
                self._require_stage(wizard, "node_ssh", entity_id)
                await self.service.replace_node_ssh(
                    entity_id,
                    username=wizard["ssh_username"],
                    port=wizard["ssh_port"],
                    auth_method=SshAuthMethod(wizard["ssh_auth_method"]),
                    staged_ref=wizard["staged_ref"],
                    public_key=wizard.get("ssh_public_key"),
                )
                context.user_data.pop(_WIZARD_KEY, None)
                await query.edit_message_text("✅ SSH credentials validated and replaced.")
                return
        except (InvalidCallbackData, ValueError) as exc:
            await self._safe_edit(query, f"❌ {self._safe_error(exc)}")
        except Exception as exc:
            logger.exception("telegram_registry_signed_action_failed")
            await self._safe_edit(query, f"❌ {self._safe_error(exc)}")

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ok, user_id = await self._authorized(update)
        if not ok or user_id is None or update.effective_message is None:
            return
        wizard = context.user_data.get(_WIZARD_KEY)
        if not isinstance(wizard, dict):
            return
        text = (update.effective_message.text or "").strip()
        stage = wizard.get("stage")
        try:
            if stage == "provider_key":
                key = text.lower()
                if not key or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in key):
                    raise ValueError("provider key must use letters, digits, '-' or '_'")
                wizard["key"] = key
                wizard["stage"] = "provider_name"
                await update.effective_message.reply_text("Display name for this provider?")
                return
            if stage == "provider_name":
                if not text:
                    raise ValueError("display name cannot be blank")
                wizard["display_name"] = text
                wizard["stage"] = "provider_token"
                await update.effective_message.reply_text(
                    "Send the provider API token. I will validate it read-only and delete the token message."
                )
                return
            if stage == "provider_token":
                await self._delete_secret_message(update)
                token = SecretStr(text)
                await self.service.validate_provider_token(ProviderType(wizard["provider_type"]), token)
                ref = self.service.stage_secret("provider", wizard["key"], token)
                wizard["staged_ref"] = ref
                wizard["stage"] = "provider_confirm"
                await update.effective_chat.send_message(
                    "✅ Provider API access verified.\n\n"
                    f"Type: {wizard['provider_type']}\nKey: {wizard['key']}\nName: {wizard['display_name']}\n\n"
                    "Save this provider?",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("✅ Save", callback_data="r.pac"),
                            InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
                        ]]
                    ),
                )
                return
            if stage == "provider_rename":
                provider_id = UUID(wizard["entity_id"])
                await self.service.rename_provider(provider_id, text)
                context.user_data.pop(_WIZARD_KEY, None)
                await update.effective_message.reply_text("✅ Provider renamed.")
                return
            if stage == "provider_token_replace":
                await self._delete_secret_message(update)
                provider_id = UUID(wizard["entity_id"])
                provider = await self.service.get_provider(provider_id)
                if provider is None:
                    raise ValueError("provider not found")
                token = SecretStr(text)
                await self.service.validate_provider_token(provider.provider_type, token)
                ref = self.service.stage_secret("provider", f"{provider.key}-replace", token)
                wizard["staged_ref"] = ref
                wizard["stage"] = "provider_token"
                signed = self.signer.encode("pc", provider_id, user_id)
                await update.effective_chat.send_message(
                    "✅ New token works. Replace the stored provider token?",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("✅ Replace", callback_data=signed),
                            InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
                        ]]
                    ),
                )
                return
            if stage == "node_server_id":
                if not text:
                    raise ValueError("provider instance/server ID cannot be blank")
                wizard["provider_server_id"] = text
                wizard["stage"] = "node_master_id"
                await update.effective_message.reply_text("3X-UI Master Node ID?")
                return
            if stage == "node_master_id":
                master_id = int(text)
                if master_id < 1:
                    raise ValueError("Master Node ID must be positive")
                wizard["master_node_id"] = master_id
                await self._try_node_discovery(update, context, node_token=None)
                return
            if stage == "node_api_token":
                await self._delete_secret_message(update)
                token = SecretStr(text)
                await self._try_node_discovery(update, context, node_token=token)
                ref = self.service.stage_secret("node-api", f"master-{wizard['master_node_id']}", token)
                wizard["node_api_token_ref"] = ref
                return
            if stage == "node_name":
                suggested = wizard["suggested_name"]
                wizard["name"] = suggested if text == "-" else text
                wizard["stage"] = "node_auth"
                await update.effective_message.reply_text(
                    "SSH authentication method?",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("🔑 Private Key", callback_data="r.naa.private_key"),
                            InlineKeyboardButton("🔐 Password", callback_data="r.naa.password"),
                        ]]
                    ),
                )
                return
            if stage == "node_ssh_username":
                wizard["ssh_username"] = "root" if text == "-" else text
                wizard["stage"] = "node_ssh_port"
                await update.effective_message.reply_text("SSH port? Send '-' for 22.")
                return
            if stage == "node_ssh_port":
                port = 22 if text == "-" else int(text)
                if not 1 <= port <= 65535:
                    raise ValueError("SSH port must be between 1 and 65535")
                wizard["ssh_port"] = port
                resume_stage = (
                    "node_ssh_public_key"
                    if wizard["ssh_auth_method"] == SshAuthMethod.PRIVATE_KEY.value
                    else "node_ssh_secret"
                )
                await self._request_ssh_host_key_confirmation(
                    update, context, user_id,
                    host=wizard["provider_ipv4"],
                    port=port,
                    resume_stage=resume_stage,
                )
                return
            if stage == "node_ssh_public_key":
                if not text.startswith("ssh-"):
                    raise ValueError("send a valid OpenSSH public key")
                wizard["ssh_public_key"] = text
                wizard["stage"] = "node_ssh_secret"
                await update.effective_message.reply_text(
                    "Send the SSH private key. I will validate it and delete the message."
                )
                return
            if stage == "node_ssh_secret":
                await self._delete_secret_message(update)
                secret = SecretStr(text)
                try:
                    await self.service.validate_ssh(
                        host=wizard["provider_ipv4"],
                        username=wizard["ssh_username"],
                        port=wizard["ssh_port"],
                        auth_method=SshAuthMethod(wizard["ssh_auth_method"]),
                        secret=secret,
                    )
                except Exception as exc:
                    if self._is_untrusted_ssh_host_key_error(exc):
                        # Do not retain the submitted secret. Ask the user to explicitly
                        # trust the observed fingerprint, then re-send the credential.
                        await self._request_ssh_host_key_confirmation(
                            update, context, user_id,
                            host=wizard["provider_ipv4"],
                            port=int(wizard["ssh_port"]),
                            resume_stage="node_ssh_secret",
                        )
                        return
                    raise
                ref = self.service.stage_secret("node-ssh", wizard["provider_server_id"], secret)
                wizard["ssh_secret_ref"] = ref
                wizard["stage"] = "node_confirm"
                await update.effective_chat.send_message(
                    self._node_add_preview(wizard),
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("✅ Save Node", callback_data="r.nac"),
                            InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
                        ]]
                    ),
                )
                return
            if stage == "node_rename":
                node_id = UUID(wizard["entity_id"])
                await self.service.rename_node(node_id, text)
                context.user_data.pop(_WIZARD_KEY, None)
                await update.effective_message.reply_text("✅ Node renamed.")
                return
            if stage == "node_token_replace":
                await self._delete_secret_message(update)
                node_id = UUID(wizard["entity_id"])
                token = SecretStr(text)
                await self.service.validate_node_api_token(node_id, token)
                ref = self.service.stage_secret("node-api", f"node-{node_id.hex}-replace", token)
                wizard["staged_ref"] = ref
                wizard["stage"] = "node_token"
                signed = self.signer.encode("nc", node_id, user_id)
                await update.effective_chat.send_message(
                    "✅ New Node API token works. Replace the stored token?",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("✅ Replace", callback_data=signed),
                            InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
                        ]]
                    ),
                )
                return
            if stage == "node_ssh_edit_username":
                wizard["ssh_username"] = "root" if text == "-" else text
                wizard["stage"] = "node_ssh_edit_port"
                await update.effective_message.reply_text("SSH port? Send '-' for 22.")
                return
            if stage == "node_ssh_edit_port":
                port = 22 if text == "-" else int(text)
                if not 1 <= port <= 65535:
                    raise ValueError("SSH port must be between 1 and 65535")
                wizard["ssh_port"] = port
                node = await self.service.get_node(UUID(wizard["entity_id"]))
                if node is None or not node.provider_ipv4:
                    raise ValueError("node/provider IP missing")
                resume_stage = (
                    "node_ssh_edit_public_key"
                    if wizard["ssh_auth_method"] == SshAuthMethod.PRIVATE_KEY.value
                    else "node_ssh_edit_secret"
                )
                await self._request_ssh_host_key_confirmation(
                    update, context, user_id,
                    host=node.provider_ipv4,
                    port=port,
                    resume_stage=resume_stage,
                )
                return
            if stage == "node_ssh_edit_public_key":
                if not text.startswith("ssh-"):
                    raise ValueError("send a valid OpenSSH public key")
                wizard["ssh_public_key"] = text
                wizard["stage"] = "node_ssh_edit_secret"
                await update.effective_message.reply_text("Send the new SSH private key.")
                return
            if stage == "node_ssh_edit_secret":
                await self._delete_secret_message(update)
                node_id = UUID(wizard["entity_id"])
                node = await self.service.get_node(node_id)
                if node is None or not node.provider_ipv4:
                    raise ValueError("node/provider IP missing")
                secret = SecretStr(text)
                try:
                    await self.service.validate_ssh(
                        host=node.provider_ipv4,
                        username=wizard["ssh_username"],
                        port=wizard["ssh_port"],
                        auth_method=SshAuthMethod(wizard["ssh_auth_method"]),
                        secret=secret,
                    )
                except Exception as exc:
                    if self._is_untrusted_ssh_host_key_error(exc):
                        await self._request_ssh_host_key_confirmation(
                            update, context, user_id,
                            host=node.provider_ipv4,
                            port=int(wizard["ssh_port"]),
                            resume_stage="node_ssh_edit_secret",
                        )
                        return
                    raise
                ref = self.service.stage_secret("node-ssh", f"node-{node_id.hex}-replace", secret)
                wizard["staged_ref"] = ref
                wizard["stage"] = "node_ssh"
                signed = self.signer.encode("sc", node_id, user_id)
                await update.effective_chat.send_message(
                    "✅ SSH access verified. Replace the stored SSH credentials?",
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("✅ Replace", callback_data=signed),
                            InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
                        ]]
                    ),
                )
                return
        except Exception as exc:
            logger.exception("telegram_registry_wizard_failed", extra={"stage": stage})
            await update.effective_chat.send_message(f"❌ {self._safe_error(exc)}")

    @staticmethod
    def _is_untrusted_ssh_host_key_error(exc: BaseException) -> bool:
        current: BaseException | None = exc
        for _ in range(6):
            if current is None:
                break
            name = type(current).__name__.lower()
            message = str(current).lower()
            if (
                "hostkeynotverifiable" in name
                or "host key is not trusted" in message
                or "host key is not trusted for host" in message
                or "host key verification failed" in message
            ):
                return True
            current = current.__cause__ or current.__context__
        return False

    async def _request_ssh_host_key_confirmation(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
        *, host: str, port: int, resume_stage: str,
    ) -> None:
        wizard = context.user_data.get(_WIZARD_KEY)
        if not isinstance(wizard, dict):
            raise ValueError("SSH setup session expired")
        candidate = await self.service.inspect_ssh_host_key(host=host, port=port)
        confirmation_id = uuid4()
        wizard.update({
            "stage": "ssh_host_key_confirm",
            "ssh_host": host,
            "ssh_host_key_algorithm": candidate.algorithm,
            "ssh_host_key_fingerprint": candidate.fingerprint,
            "host_key_confirmation_id": str(confirmation_id),
            "host_key_resume_stage": resume_stage,
        })
        signed = self.signer.encode("hk", confirmation_id, user_id)
        await update.effective_chat.send_message(
            "🔐 SSH host identity confirmation\n\n"
            f"Host: {host}:{port}\n"
            f"Algorithm: {candidate.algorithm}\n"
            f"SHA256 fingerprint: `{candidate.fingerprint}`\n\n"
            "Confirm only if this fingerprint belongs to the VPS you intend to manage. "
            "ASO will keep strict SSH host-key verification enabled.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Trust this fingerprint", callback_data=signed),
                InlineKeyboardButton("❌ Cancel", callback_data="r.cancel"),
            ]]),
        )

    @staticmethod
    def _ssh_secret_prompt(stage: str) -> str:
        return {
            "node_ssh_public_key": "Send the matching SSH public key used for provisioning replacement VPSs.",
            "node_ssh_secret": "Send the SSH password. I will validate it and delete the message.",
            "node_ssh_edit_public_key": "Send the matching SSH public key.",
            "node_ssh_edit_secret": "Send the new SSH password/private key. It will be validated and the message deleted.",
        }.get(stage, "Continue the SSH credential setup.")

    async def _provider_action(self, query: Any, context: ContextTypes.DEFAULT_TYPE, user_id: int, data: str) -> None:
        parts = data.split(".")
        if len(parts) < 3:
            return
        if parts[2] == "test" and len(parts) == 4:
            provider_id = UUID(hex=parts[3])
            await self.service.test_provider(provider_id)
            await query.edit_message_text("✅ Provider API access is working.", reply_markup=self._back_provider(provider_id))
            return
        if parts[2] == "name" and len(parts) == 4:
            provider_id = UUID(hex=parts[3])
            context.user_data[_WIZARD_KEY] = {"stage": "provider_rename", "entity_id": str(provider_id)}
            await query.edit_message_text("Send the new provider display name.", reply_markup=self._cancel_keyboard())
            return
        if parts[2] == "token" and len(parts) == 4:
            provider_id = UUID(hex=parts[3])
            context.user_data[_WIZARD_KEY] = {"stage": "provider_token_replace", "entity_id": str(provider_id)}
            await query.edit_message_text("Send the new provider API token. It will be validated before replacement.", reply_markup=self._cancel_keyboard())
            return
        if parts[2] == "toggle" and len(parts) == 4:
            provider_id = UUID(hex=parts[3])
            provider = await self.service.get_provider(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            await self.runtime.control.set_provider_active(provider_id, not provider.is_active, actor_user_id=user_id)
            await self._show_provider(query, provider_id, user_id)
            return
        if parts[2] == "remove" and len(parts) == 4:
            provider_id = UUID(hex=parts[3])
            signed = self.signer.encode("px", provider_id, user_id)
            await query.edit_message_text(
                "Remove this provider from the ASO registry?\nNo provider VPS will be deleted.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Remove from ASO", callback_data=signed), InlineKeyboardButton("Cancel", callback_data=f"r.p.{provider_id.hex}")]]),
            )
            return
        provider_id = UUID(hex=parts[2])
        await self._show_provider(query, provider_id, user_id)

    async def _node_action(self, query: Any, context: ContextTypes.DEFAULT_TYPE, user_id: int, data: str) -> None:
        parts = data.split(".")
        if len(parts) < 3:
            return
        if parts[2] == "test" and len(parts) == 4:
            node_id = UUID(hex=parts[3])
            discovery = await self.service.test_node(node_id)
            await query.edit_message_text(
                "✅ Provider + Master + Node API + SSH checks passed.\n\n" + self._safe_discovery(discovery),
                reply_markup=self._back_node(node_id),
            )
            return
        if parts[2] == "name" and len(parts) == 4:
            node_id = UUID(hex=parts[3])
            context.user_data[_WIZARD_KEY] = {"stage": "node_rename", "entity_id": str(node_id)}
            await query.edit_message_text("Send the new node name.", reply_markup=self._cancel_keyboard())
            return
        if parts[2] == "token" and len(parts) == 4:
            node_id = UUID(hex=parts[3])
            context.user_data[_WIZARD_KEY] = {"stage": "node_token_replace", "entity_id": str(node_id)}
            await query.edit_message_text("Send the new 3X-UI Node API token. It will be validated before save.", reply_markup=self._cancel_keyboard())
            return
        if parts[2] == "ssh" and len(parts) == 4:
            node_id = UUID(hex=parts[3])
            context.user_data[_WIZARD_KEY] = {"stage": "node_ssh_edit_auth", "entity_id": str(node_id)}
            await query.edit_message_text(
                "Choose new SSH authentication method.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Private Key", callback_data=f"r.nsa.private_key.{node_id.hex}"), InlineKeyboardButton("🔐 Password", callback_data=f"r.nsa.password.{node_id.hex}")], [InlineKeyboardButton("Cancel", callback_data="r.cancel")]]),
            )
            return
        if parts[2] == "remove" and len(parts) == 4:
            node_id = UUID(hex=parts[3])
            signed = self.signer.encode("nx", node_id, user_id)
            await query.edit_message_text(
                "Remove this node from ASO registry only?\nThe VPS and Master node will NOT be deleted or modified. Nodes with replacement history are protected from hard removal.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Remove from ASO", callback_data=signed), InlineKeyboardButton("Cancel", callback_data=f"r.n.{node_id.hex}")]]),
            )
            return
        node_id = UUID(hex=parts[2])
        await self._show_node(query, node_id, user_id)

    async def _node_ssh_edit_auth_selected(
        self,
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
        data: str,
    ) -> None:
        parts = data.split(".")
        if len(parts) != 4:
            raise ValueError("invalid SSH edit action")
        auth = SshAuthMethod(parts[2])
        node_id = UUID(hex=parts[3])
        wizard = context.user_data.get(_WIZARD_KEY)
        if not isinstance(wizard, dict) or wizard.get("entity_id") != str(node_id):
            raise ValueError("SSH edit session expired")
        wizard["ssh_auth_method"] = auth.value
        wizard["stage"] = "node_ssh_edit_username"
        await query.edit_message_text(
            "SSH username? Send '-' for root.",
            reply_markup=self._cancel_keyboard(),
        )

    async def _start_provider_add(self, query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._cancel_wizard(context)
        context.user_data[_WIZARD_KEY] = {"stage": "provider_type"}
        await query.edit_message_text(
            "Choose provider type.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Linode / Akamai", callback_data="r.pat.linode"), InlineKeyboardButton("Hetzner", callback_data="r.pat.hetzner")], [InlineKeyboardButton("Cancel", callback_data="r.cancel")]]),
        )

    async def _provider_type_selected(self, query: Any, context: ContextTypes.DEFAULT_TYPE, raw: str) -> None:
        provider_type = ProviderType(raw)
        context.user_data[_WIZARD_KEY] = {"stage": "provider_key", "provider_type": provider_type.value}
        await query.edit_message_text("Short unique provider key? Example: linode-main", reply_markup=self._cancel_keyboard())

    async def _commit_provider_add(self, query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        wizard = self._wizard(context, "provider_confirm")
        ref = wizard.get("staged_ref")
        try:
            provider = await self.service.commit_provider(
                key=wizard["key"],
                display_name=wizard["display_name"],
                provider_type=ProviderType(wizard["provider_type"]),
                staged_credential_ref=ref,
            )
        except Exception:
            raise
        context.user_data.pop(_WIZARD_KEY, None)
        await query.edit_message_text(f"✅ Provider {provider.display_name} added and API access verified.")

    async def _start_node_add(self, query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._cancel_wizard(context)
        providers = [p for p in await self.service.list_providers() if p.is_active]
        if not providers:
            await query.edit_message_text("Add and validate a provider first.")
            return
        context.user_data[_WIZARD_KEY] = {"stage": "node_provider"}
        rows = [[InlineKeyboardButton(p.display_name, callback_data=f"r.nap.{p.id.hex}")] for p in providers[:30]]
        rows.append([InlineKeyboardButton("Cancel", callback_data="r.cancel")])
        await query.edit_message_text("Choose the provider that owns the existing VPS.", reply_markup=InlineKeyboardMarkup(rows))

    async def _node_provider_selected(self, query: Any, context: ContextTypes.DEFAULT_TYPE, raw_id: str) -> None:
        provider_id = UUID(hex=raw_id)
        provider = await self.service.get_provider(provider_id)
        if provider is None or not provider.is_active:
            raise ValueError("provider is missing or disabled")
        context.user_data[_WIZARD_KEY] = {"stage": "node_server_id", "provider_id": str(provider_id), "provider_name": provider.display_name}
        await query.edit_message_text(
            "Send only the existing Provider Instance/Server ID.\nASO will discover IP, region, plan/type and image automatically.",
            reply_markup=self._cancel_keyboard(),
        )

    async def _try_node_discovery(self, update: Update, context: ContextTypes.DEFAULT_TYPE, node_token: SecretStr | None) -> None:
        wizard = context.user_data[_WIZARD_KEY]
        try:
            discovery = await self.service.discover_node(
                provider_id=UUID(wizard["provider_id"]),
                provider_server_id=wizard["provider_server_id"],
                master_node_id=int(wizard["master_node_id"]),
                node_api_token=node_token,
            )
        except ValueError as exc:
            if node_token is None and "api token" in str(exc).lower():
                wizard["stage"] = "node_api_token"
                await update.effective_chat.send_message(
                    "Master reports this node uses an API token. Send the current 3X-UI Node API token; it will be validated and the message deleted.",
                    reply_markup=self._cancel_keyboard(),
                )
                return
            raise
        wizard.update(
            {
                "suggested_name": discovery.suggested_name,
                "provider_ipv4": discovery.provider_host,
                "provider_region": discovery.server.region,
                "provider_server_type": discovery.server.server_type,
                "provider_image": discovery.server.image,
                "master_address": discovery.master.address,
                "master_port": discovery.master.port,
                "master_base_path": discovery.master.base_path,
                "stage": "node_name",
            }
        )
        await update.effective_chat.send_message(
            "✅ Provider instance and Master node verified.\n\n"
            + self._safe_discovery(discovery)
            + f"\n\nSend node name, or '-' to use: {discovery.suggested_name}",
            reply_markup=self._cancel_keyboard(),
        )

    async def _node_auth_selected(self, query: Any, context: ContextTypes.DEFAULT_TYPE, raw: str) -> None:
        wizard = self._wizard(context, "node_auth")
        auth = SshAuthMethod(raw)
        wizard["ssh_auth_method"] = auth.value
        wizard["stage"] = "node_ssh_username"
        await query.edit_message_text("SSH username? Send '-' for root.", reply_markup=self._cancel_keyboard())

    async def _commit_node_add(self, query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
        wizard = self._wizard(context, "node_confirm")
        node = await self.service.commit_node(
            provider_id=UUID(wizard["provider_id"]),
            provider_server_id=wizard["provider_server_id"],
            master_node_id=int(wizard["master_node_id"]),
            name=wizard.get("name"),
            node_api_token_ref=wizard.get("node_api_token_ref"),
            ssh_username=wizard["ssh_username"],
            ssh_port=int(wizard["ssh_port"]),
            ssh_auth_method=SshAuthMethod(wizard["ssh_auth_method"]),
            ssh_secret_ref=wizard["ssh_secret_ref"],
            ssh_public_key=wizard.get("ssh_public_key"),
        )
        context.user_data.pop(_WIZARD_KEY, None)
        await query.edit_message_text(
            f"✅ Node {node.name} added. Provider, Master, Node API (when required) and SSH access were verified."
        )

    async def _show_provider(self, query: Any, provider_id: UUID, user_id: int) -> None:
        provider = await self.service.get_provider(provider_id)
        if provider is None:
            raise ValueError("provider not found")
        text = (
            f"☁️ {provider.display_name}\n"
            f"Type: {provider.provider_type.value}\n"
            f"Key: {provider.key}\n"
            f"Status: {'ACTIVE' if provider.is_active else 'DISABLED'}\n"
            f"Nodes: {provider.node_count}\n"
            "Credential: configured (hidden)"
        )
        rows = [
            [InlineKeyboardButton("🧪 Test API", callback_data=f"r.p.test.{provider.id.hex}"), InlineKeyboardButton("✏️ Rename", callback_data=f"r.p.name.{provider.id.hex}")],
            [InlineKeyboardButton("🔑 Replace API Token", callback_data=f"r.p.token.{provider.id.hex}"), InlineKeyboardButton("⏯ Enable/Disable", callback_data=f"r.p.toggle.{provider.id.hex}")],
            [InlineKeyboardButton("🗑 Remove from ASO", callback_data=f"r.p.remove.{provider.id.hex}")],
            [InlineKeyboardButton("⬅️ Providers", callback_data="r.providers")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _show_node(self, query: Any, node_id: UUID, user_id: int) -> None:
        node = await self.service.get_node(node_id)
        if node is None:
            raise ValueError("node not found")
        text = (
            f"🖥 {node.name}\n"
            f"Provider: {node.provider_key} ({node.provider_type.value})\n"
            f"Instance ID: {node.provider_server_id}\n"
            f"Provider IPv4: {node.provider_ipv4 or '-'}\n"
            f"Region: {node.provider_region or '-'}\n"
            f"Plan/Type: {node.provider_server_type or '-'}\n"
            f"Image: {node.provider_image or '-'}\n"
            f"Master Node ID: {node.master_node_id}\n"
            f"Monitor endpoint: {node.monitoring_host}:{node.monitoring_port}\n"
            f"SSH: {node.ssh_username}@{node.provider_ipv4 or '-'}:{node.ssh_port} ({node.ssh_auth_method.value})\n"
            f"Node API Token: {'configured' if node.has_node_api_token else 'not configured'}"
        )
        rows = [
            [InlineKeyboardButton("⚙️ Monitoring / Repair", callback_data=f"o.n.{node.id.hex}")],
            [InlineKeyboardButton("⚠️ Force Repair", callback_data=f"fr.{node.id.hex}")],
            [InlineKeyboardButton("🧪 Test All Access", callback_data=f"r.n.test.{node.id.hex}"), InlineKeyboardButton("✏️ Rename", callback_data=f"r.n.name.{node.id.hex}")],
            [InlineKeyboardButton("🔑 Replace Node API Token", callback_data=f"r.n.token.{node.id.hex}"), InlineKeyboardButton("🔐 Replace SSH", callback_data=f"r.n.ssh.{node.id.hex}")],
            [InlineKeyboardButton("🗑 Remove from ASO", callback_data=f"r.n.remove.{node.id.hex}")],
            [InlineKeyboardButton("⬅️ Nodes", callback_data="r.nodes")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    async def _authorized(self, update: Update) -> tuple[bool, int | None]:
        user_id = update.effective_user.id if update.effective_user else None
        if self.authorizer.is_authorized(user_id):
            return True, user_id
        if update.callback_query:
            await update.callback_query.answer("Access denied.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("Access denied.")
        return False, user_id

    async def _cancel_wizard(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        wizard = context.user_data.pop(_WIZARD_KEY, None)
        if not isinstance(wizard, dict):
            return
        for key in ("staged_ref", "node_api_token_ref", "ssh_secret_ref"):
            self.service.discard_staged_secret(wizard.get(key))

    @staticmethod
    def _wizard(context: ContextTypes.DEFAULT_TYPE, expected_stage: str) -> dict[str, Any]:
        wizard = context.user_data.get(_WIZARD_KEY)
        if not isinstance(wizard, dict) or wizard.get("stage") != expected_stage:
            raise ValueError("this setup action expired; start it again")
        return wizard

    @staticmethod
    def _require_stage(wizard: dict[str, Any], stage: str, entity_id: UUID) -> None:
        if wizard.get("stage") != stage or wizard.get("entity_id") != str(entity_id):
            raise ValueError("this confirmation no longer matches the active edit")

    async def _delete_secret_message(self, update: Update) -> None:
        try:
            if update.effective_message is not None:
                await update.effective_message.delete()
        except BadRequest:
            # Bot may not have deletion permission in every chat. Secrets still never enter logs/DB.
            pass

    @staticmethod
    def _safe_discovery(discovery: Any) -> str:
        warning = ""
        if discovery.warnings:
            warning = "\nWarnings: " + "; ".join(discovery.warnings)
        return (
            f"Provider VPS: {discovery.server.name} / {discovery.server.provider_server_id}\n"
            f"IPv4: {discovery.server.ipv4}\n"
            f"Region: {discovery.server.region}\n"
            f"Plan/Type: {discovery.server.server_type}\n"
            f"Image: {discovery.server.image}\n"
            f"Master: {discovery.master.name} / ID {discovery.master.id}\n"
            f"Node endpoint: {discovery.master.address}:{discovery.master.port}"
            f"{warning}"
        )

    @staticmethod
    def _node_add_preview(wizard: dict[str, Any]) -> str:
        return (
            "✅ Provider/Master/SSH validation passed.\n\n"
            f"Name: {wizard['name']}\n"
            f"Provider: {wizard['provider_name']}\n"
            f"Instance ID: {wizard['provider_server_id']}\n"
            f"IPv4: {wizard['provider_ipv4']}\n"
            f"Region: {wizard['provider_region']}\n"
            f"Plan/Type: {wizard['provider_server_type']}\n"
            f"Image: {wizard['provider_image']}\n"
            f"Master Node ID: {wizard['master_node_id']}\n"
            f"Master endpoint: {wizard['master_address']}:{wizard['master_port']}\n"
            f"SSH: {wizard['ssh_username']}@{wizard['provider_ipv4']}:{wizard['ssh_port']}\n\n"
            "Save this node to ASO registry?"
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        lowered = text.lower()
        if any(token in lowered for token in ("token=", "password=", "authorization:")):
            return "operation failed; sensitive details were hidden. Check service logs."
        return text[:800]

    @staticmethod
    def _cancel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="r.cancel")]])

    @staticmethod
    def _back_provider(provider_id: UUID) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Provider", callback_data=f"r.p.{provider_id.hex}")]])

    @staticmethod
    def _back_node(node_id: UUID) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Node", callback_data=f"r.n.{node_id.hex}")]])

    @staticmethod
    async def _edit_or_reply(target: Any, text: str, markup: InlineKeyboardMarkup) -> None:
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text, reply_markup=markup)
        else:
            await target.reply_text(text, reply_markup=markup)

    @staticmethod
    async def _safe_edit(query: Any, text: str) -> None:
        try:
            await query.edit_message_text(text)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
