from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.bot.auth import TelegramAuthorizer
from app.bot.callbacks import CallbackSigner, InvalidCallbackData


def test_authorizer_is_default_deny() -> None:
    auth = TelegramAuthorizer((100, 200))
    assert auth.is_authorized(100)
    assert not auth.is_authorized(300)
    assert not auth.is_authorized(None)


def test_callback_is_user_bound_signed_and_expiring() -> None:
    signer = CallbackSigner(SecretStr("s" * 32), ttl_minutes=10)
    entity_id = uuid4()
    encoded = signer.encode("rc", entity_id, 100, now=6000)
    assert len(encoded.encode()) <= 64

    verified = signer.verify(encoded, 100, expected_action="rc", now=6060)
    assert verified.entity_id == entity_id

    with pytest.raises(InvalidCallbackData):
        signer.verify(encoded, 101, now=6060)
    with pytest.raises(InvalidCallbackData):
        signer.verify(encoded, 100, now=6000 + 11 * 60)
