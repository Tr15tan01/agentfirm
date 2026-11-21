"""Grant platform super-admin to an existing user. Run by an operator with the OWNER
database role — there is deliberately no HTTP endpoint that can do this.

    AGENTFIRM_MIGRATIONS_DATABASE_URL=... python -m scripts.create_superadmin user@example.com
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


async def main(email: str) -> None:
    dsn = os.environ["AGENTFIRM_MIGRATIONS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        uid = await conn.fetchval("UPDATE users SET is_super_admin = true WHERE lower(email) = lower($1) RETURNING id", email)
        if uid is None:
            sys.exit(f"No user with email {email}")
        await conn.execute(
            "SELECT log_platform_audit('platform.super_admin_granted', 'user', $1::text, NULL, 'cli', jsonb_build_object('email', $2::text))", str(uid), email
        )
        print(f"Granted super-admin to {email} ({uid})")
    finally:
        await conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.create_superadmin <email>")
    asyncio.run(main(sys.argv[1]))
