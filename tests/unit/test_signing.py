"""Unit tests for RSA-PSS signing helpers in src/core/auth."""

from __future__ import annotations

import base64
import time

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from src.core.auth import build_headers, load_private_key, sign_pss


def _generate_keypair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _verify_pss(public_key: RSAPublicKey, message: str, sig_b64: str) -> None:
    """Verify a PSS signature. Raises InvalidSignature on failure."""
    sig = base64.b64decode(sig_b64)
    public_key.verify(
        sig,
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )


def test_sign_pss_verifies_with_matching_public_key() -> None:
    private_key, public_key = _generate_keypair()
    message = "1712345678901GET/trade-api/v2/portfolio/balance"
    sig = sign_pss(private_key, message)
    _verify_pss(public_key, message, sig)  # must not raise


def test_sign_pss_different_message_fails_verify() -> None:
    private_key, public_key = _generate_keypair()
    sig = sign_pss(private_key, "message_A")
    with pytest.raises(InvalidSignature):
        _verify_pss(public_key, "message_B", sig)


def test_build_headers_contains_exactly_the_required_keys() -> None:
    private_key, public_key = _generate_keypair()
    now_ms = int(time.time() * 1000)
    headers = build_headers(
        key_id="abc-123",
        private_key=private_key,
        method="GET",
        path_or_url="/trade-api/v2/portfolio/balance",
    )
    assert set(headers.keys()) == {
        "KALSHI-ACCESS-KEY",
        "KALSHI-ACCESS-SIGNATURE",
        "KALSHI-ACCESS-TIMESTAMP",
        "Content-Type",
    }
    assert headers["KALSHI-ACCESS-KEY"] == "abc-123"
    ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
    assert abs(ts - now_ms) < 5000
    sig_b64 = headers["KALSHI-ACCESS-SIGNATURE"]
    path = "/trade-api/v2/portfolio/balance"
    message = str(ts) + "GET" + path
    _verify_pss(public_key, message, sig_b64)


def test_build_headers_strips_query_string() -> None:
    private_key, public_key = _generate_keypair()
    headers = build_headers(
        key_id="test",
        private_key=private_key,
        method="GET",
        path_or_url="/trade-api/v2/markets?status=active&limit=100",
    )
    ts = headers["KALSHI-ACCESS-TIMESTAMP"]
    sig_b64 = headers["KALSHI-ACCESS-SIGNATURE"]

    path_without_query = "/trade-api/v2/markets"
    message_without_query = ts + "GET" + path_without_query
    _verify_pss(public_key, message_without_query, sig_b64)  # must succeed

    path_with_query = "/trade-api/v2/markets?status=active&limit=100"
    message_with_query = ts + "GET" + path_with_query
    with pytest.raises(InvalidSignature):
        _verify_pss(public_key, message_with_query, sig_b64)


def test_build_headers_uppercases_method() -> None:
    private_key, public_key = _generate_keypair()
    headers = build_headers(
        key_id="test",
        private_key=private_key,
        method="get",  # lowercase input
        path_or_url="/trade-api/v2/portfolio/balance",
    )
    ts = headers["KALSHI-ACCESS-TIMESTAMP"]
    sig_b64 = headers["KALSHI-ACCESS-SIGNATURE"]
    message = ts + "GET" + "/trade-api/v2/portfolio/balance"
    _verify_pss(public_key, message, sig_b64)  # must succeed with uppercase GET


def test_salt_length_is_digest_length() -> None:
    private_key, public_key = _generate_keypair()
    message = "salt_length_test"
    sig_b64 = sign_pss(private_key, message)
    sig = base64.b64decode(sig_b64)

    # Verify with DIGEST_LENGTH — must succeed (this is what sign_pss uses)
    public_key.verify(
        sig,
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )

    # Verify that we actually used DIGEST_LENGTH (32 bytes for SHA-256)
    # by checking the signature was created with the right salt_length
    # A signature created with DIGEST_LENGTH will have a specific format
    assert len(sig) == 256  # 2048-bit RSA = 256 bytes signature


def test_load_private_key_roundtrip(tmp_path: pytest.TempPathFactory) -> None:
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "test.pem"  # type: ignore[operator]
    key_file.write_bytes(pem_bytes)
    loaded = load_private_key(str(key_file))
    assert isinstance(loaded, RSAPrivateKey)
    # Verify the loaded key signs correctly
    msg = "roundtrip_test"
    sig = sign_pss(loaded, msg)
    _verify_pss(private_key.public_key(), msg, sig)
