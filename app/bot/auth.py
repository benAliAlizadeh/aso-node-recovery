from __future__ import annotations


class TelegramAuthorizer:
    def __init__(self, authorized_user_ids: tuple[int, ...]) -> None:
        self._authorized = frozenset(authorized_user_ids)

    def is_authorized(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self._authorized
