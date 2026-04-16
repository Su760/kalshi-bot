"""RSA-PSS signing helpers for Kalshi API authentication."""

from __future__ import annotations

import base64
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def load_private_key(path: str) -> RSAPrivateKey:
    """Load PEM-encoded RSA private key. Supports PKCS#1 and PKCS#8."""
    with open(path, "rb") as f:
        pem_data = f.read()
    key = serialization.load_pem_private_key(pem_data, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError(f"Expected RSA private key, got {type(key)}")
    return key


def sign_pss(private_key: RSAPrivateKey, message: str) -> str:
    """RSA-PSS / SHA-256 / MGF1-SHA256 / salt=DIGEST_LENGTH. Returns base64 string."""
    sig = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,  # 32 bytes. NEVER MAX_LENGTH.
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")


def build_headers(
    key_id: str,
    private_key: RSAPrivateKey,
    method: str,
    path_or_url: str,
) -> dict[str, str]:
    """
    Returns the three signing headers (+ Content-Type: application/json).
    method is uppercased internally. path_or_url is stripped to path-only
    via urllib.parse.urlsplit. timestamp is integer ms, serialized as str.
    """
    timestamp_ms = str(int(time.time() * 1000))
    method_upper = method.upper()
    path = urllib.parse.urlsplit(path_or_url).path
    message = timestamp_ms + method_upper + path
    signature = sign_pss(private_key, message)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json",
    }
