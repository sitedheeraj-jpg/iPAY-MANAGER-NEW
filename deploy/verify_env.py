"""Validate deployment configuration and MongoDB connectivity.

Run from the project root after setting environment variables:

    python -m deploy.verify_env
"""

import asyncio
import logging
import sys

from pydantic import ValidationError

from app.config import get_settings
from app.database import MongoStore


async def verify() -> int:
    logging.basicConfig(level=logging.WARNING)
    try:
        settings = get_settings()
    except ValidationError as exc:
        print("Configuration check: FAILED")
        for error in exc.errors():
            print(f"- {'.'.join(str(part) for part in error['loc'])}: {error['msg']}")
        return 1

    if not settings.owner_ids:
        print("Configuration check: FAILED")
        print("- OWNER_IDS (or legacy ADMIN_IDS) must contain at least one Telegram numeric ID.")
        return 1

    store = MongoStore(settings)
    try:
        await store.connect()
    except Exception as exc:
        print("MongoDB connectivity check: FAILED")
        print(f"- {type(exc).__name__}: {exc}")
        return 1
    finally:
        await store.close()

    print("Configuration check: OK")
    print("MongoDB connectivity check: OK")
    print(f"Database: {settings.mongodb_db}")
    print(f"Configured owners: {len(settings.owner_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(verify()))