"""Rotate AGENTFIRM_MASTER_KEY (the key that wraps every stored provider/connector secret).

Envelope encryption means only the per-secret data keys are re-wrapped; the secrets themselves
are not re-encrypted. Runs in ONE transaction as the OWNER role and verifies every secret still
decrypts with the new key before committing, so a failure leaves the database unchanged.

    AGENTFIRM_MIGRATIONS_DATABASE_URL=... AGENTFIRM_MASTER_KEY=<old> AGENTFIRM_NEW_MASTER_KEY=<new> \\
        python -m scripts.rotate_master_key [--commit]

Without --commit it is a dry run (rolls back). After committing, set AGENTFIRM_MASTER_KEY=<new>
in .env.production and redeploy; until then the running app cannot read secrets saved before.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys

import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# (table, id column used in the AAD, AAD builder) — must match gateway/service._aad and integrations/router.aad.
TABLES = (
    (
        "provider_credentials",
        "SELECT id, provider_id, NULL::uuid AS org_id, ciphertext, nonce, wrapped_key, key_nonce FROM provider_credentials",
        lambda r: f"provider:{r['provider_id']}".encode(),
    ),
    (
        "connections",
        "SELECT id, NULL::uuid AS provider_id, org_id, ciphertext, nonce, wrapped_key, key_nonce FROM connections WHERE wrapped_key IS NOT NULL",
        lambda r: f"connection:{r['org_id']}:{r['id']}".encode(),
    ),
)


def _key(name: str) -> bytes:
    raw = base64.b64decode(os.environ[name])
    if len(raw) != 32:
        sys.exit(f"{name} must be base64 of 32 bytes")
    return raw


async def rotate(dsn: str, old: bytes, new: bytes, *, commit: bool) -> dict[str, int]:
    old_k, new_k = AESGCM(old), AESGCM(new)
    conn = await asyncpg.connect(dsn)
    counts: dict[str, int] = {}
    try:
        tx = conn.transaction()
        await tx.start()
        try:
            for table, query, aad_of in TABLES:
                rows = await conn.fetch(query + " FOR UPDATE")
                for r in rows:
                    aad = aad_of(r)
                    data_key = old_k.decrypt(r["key_nonce"], r["wrapped_key"], aad)  # raises if the old key is wrong
                    nonce = os.urandom(12)
                    wrapped = new_k.encrypt(nonce, data_key, aad)
                    AESGCM(new_k.decrypt(nonce, wrapped, aad)).decrypt(r["nonce"], r["ciphertext"], aad)  # verify end to end
                    await conn.execute(f"UPDATE {table} SET wrapped_key = $1, key_nonce = $2, key_id = 'master-rotated' WHERE id = $3", wrapped, nonce, r["id"])  # nosec B608 - fixed table names
                counts[table] = len(rows)
            await conn.execute(
                "SELECT log_platform_audit('platform.master_key_rotated', 'system', 'master_key', NULL, 'cli', $1::jsonb)",
                json.dumps({**counts, "committed": commit}),
            )
        except Exception:
            await tx.rollback()
            raise
        if commit:
            await tx.commit()
        else:
            await tx.rollback()
    finally:
        await conn.close()
    return counts


def main() -> None:
    commit = "--commit" in sys.argv[1:]
    dsn = os.environ["AGENTFIRM_MIGRATIONS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    counts = asyncio.run(rotate(dsn, _key("AGENTFIRM_MASTER_KEY"), _key("AGENTFIRM_NEW_MASTER_KEY"), commit=commit))
    print(("Rotated" if commit else "Dry run OK (nothing changed) for"), ", ".join(f"{n} {t}" for t, n in counts.items()))


if __name__ == "__main__":
    main()
