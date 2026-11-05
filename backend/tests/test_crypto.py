import pytest
from cryptography.fernet import InvalidToken

from app.config import get_settings
from app.crypto import decrypt, encrypt


def test_encrypt_roundtrip(settings):
    token = encrypt("mot-de-passe-secret")
    assert "mot-de-passe-secret" not in token
    assert decrypt(token) == "mot-de-passe-secret"


def test_decrypt_with_other_key_fails(settings, monkeypatch):
    token = encrypt("abc")
    monkeypatch.setenv("MP_SECRET_KEY", "autre-cle")
    get_settings.cache_clear()
    with pytest.raises(InvalidToken):
        decrypt(token)
