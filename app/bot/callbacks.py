from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr


class InvalidCallbackData(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedCallback:
    action: str
    entity_id: UUID


class CallbackSigner:
    """Stateless, user-bound, short-lived Telegram callback signatures."""

    def __init__(self, secret: SecretStr, *, ttl_minutes: int = 10) -> None:
        value = secret.get_secret_value().encode("utf-8")
        if len(value) < 32:
            raise ValueError("callback signing secret must be at least 32 bytes")
        self._secret = value
        self.ttl_minutes = ttl_minutes

    def encode(self, action: str, entity_id: UUID, user_id: int, *, now: int | None = None) -> str:
        self._validate_action(action)
        minute = (now if now is not None else int(time.time())) // 60
        stamp = f"{minute:08x}"
        payload = f"{action}.{entity_id.hex}.{stamp}"
        signature = self._signature(payload, user_id)
        encoded = f"{payload}.{signature}"
        if len(encoded.encode("utf-8")) > 64:
            raise ValueError("callback payload exceeds Telegram's 64-byte limit")
        return encoded

    def verify(
        self,
        data: str,
        user_id: int,
        *,
        expected_action: str | None = None,
        now: int | None = None,
    ) -> VerifiedCallback:
        parts = data.split(".")
        if len(parts) != 4:
            raise InvalidCallbackData("malformed callback")
        action, raw_id, stamp, supplied_signature = parts
        self._validate_action(action)
        if expected_action is not None and action != expected_action:
            raise InvalidCallbackData("unexpected callback action")

        try:
            entity_id = UUID(hex=raw_id)
            issued_minute = int(stamp, 16)
        except (ValueError, TypeError) as exc:
            raise InvalidCallbackData("malformed callback identity") from exc

        current_minute = (now if now is not None else int(time.time())) // 60
        if issued_minute > current_minute + 1:
            raise InvalidCallbackData("callback timestamp is in the future")
        if current_minute - issued_minute > self.ttl_minutes:
            raise InvalidCallbackData("callback confirmation expired")

        payload = f"{action}.{entity_id.hex}.{stamp}"
        expected = self._signature(payload, user_id)
        if not hmac.compare_digest(expected, supplied_signature):
            raise InvalidCallbackData("callback signature mismatch")
        return VerifiedCallback(action=action, entity_id=entity_id)

    def _signature(self, payload: str, user_id: int) -> str:
        message = f"{user_id}:{payload}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()[:12]

    @staticmethod
    def _validate_action(action: str) -> None:
        if len(action) != 2 or not action.isascii() or not action.isalpha():
            raise InvalidCallbackData("callback action must be a two-letter ASCII code")
