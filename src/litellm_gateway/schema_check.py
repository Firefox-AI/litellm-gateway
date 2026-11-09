"""Hold a new pod until the database has every migration this image ships.

A partial Argo CD sync skips the litellm-migrations Job, so the pod checks for
itself. Extra migrations in the database (a newer release) are fine.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

TAG = "[litellm-schema-check]"
APPLIED_SQL = (
    'SELECT migration_name FROM "_prisma_migrations" '
    "WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL"
)


def shipped_migrations():
    import litellm_proxy_extras

    migrations = Path(litellm_proxy_extras.__file__).parent / "migrations"
    shipped = {p.name for p in migrations.iterdir() if p.is_dir()}
    if not shipped:
        sys.exit(f"{TAG} no migrations found in {migrations}")
    return shipped


async def applied_migrations(url):
    from prisma import Prisma

    db = Prisma(datasource={"url": url})
    await db.connect()
    try:
        rows = await db.query_raw(APPLIED_SQL)
    finally:
        await db.disconnect()
    return {row["migration_name"] for row in rows}


def wait_for_schema(read_applied, shipped, timeout_s, interval_s):
    start = time.monotonic()
    while True:
        try:
            missing = shipped - read_applied()
            if not missing:
                elapsed = time.monotonic() - start
                print(f"{TAG} all {len(shipped)} migrations applied in {elapsed:.1f}s")
                return True
            status = f"{len(missing)} migrations pending, oldest {min(missing)}"
        except Exception as e:
            status = f"database not reachable: {str(e).splitlines()[0]}"
        if time.monotonic() - start >= timeout_s:
            print(f"{TAG} gave up after {timeout_s}s ({status})")
            print(f"{TAG} did the litellm-migrations Job run?")
            return False
        print(f"{TAG} {status}, waiting", flush=True)
        time.sleep(interval_s)


def main():
    env = os.environ
    url = (
        f"postgresql://{env['DATABASE_USERNAME']}:{env['DATABASE_PASSWORD']}"
        f"@{env['DATABASE_HOST']}:{env['DATABASE_PORT']}/{env['DATABASE_NAME']}"
        "?pgbouncer=true"
    )
    ready = wait_for_schema(
        lambda: asyncio.run(applied_migrations(url)),
        shipped_migrations(),
        timeout_s=int(env.get("MIGRATION_CHECK_TIMEOUT_S", "300")),
        interval_s=int(env.get("MIGRATION_CHECK_INTERVAL_S", "5")),
    )
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
