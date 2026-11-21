"""Envelope encryption for provider credentials (AES-256-GCM).

Each secret gets a fresh 256-bit data key; the data key is wrapped by the master
key. Only ciphertext, nonces and the last 4 characters are stored. Plaintext is
decrypted in-memory by workers at call time and never returned by any API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

KEY_ID = "master-v1"


@dataclass(frozen=True, slots=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    wrapped_key: bytes
    key_nonce: bytes
    key_id: str
    last4: str


def seal(plaintext: str, *, aad: bytes) -> Sealed:
    master = AESGCM(get_settings().resolved_master_key())
    data_key = AESGCM.generate_key(bit_length=256)
    nonce, key_nonce = os.urandom(12), os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode(), aad)
    wrapped = master.encrypt(key_nonce, data_key, aad)
    return Sealed(ciphertext, nonce, wrapped, key_nonce, KEY_ID, plaintext[-4:] if len(plaintext) >= 8 else "••••")


def open_sealed(s: Sealed, *, aad: bytes) -> str:
    master = AESGCM(get_settings().resolved_master_key())
    data_key = master.decrypt(s.key_nonce, s.wrapped_key, aad)
    return AESGCM(data_key).decrypt(s.nonce, s.ciphertext, aad).decode()
