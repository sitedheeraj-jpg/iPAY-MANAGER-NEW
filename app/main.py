import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot_commands import register_bot_commands
from app.config import get_settings
from app.database import MongoStore
from app.handlers import admin, broadcast, start, user


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if not settings.owner_ids:
        logging.getLogger(__name__).warning(
            "ADMIN_IDS is empty; no one can access /admin."
        )

    store = MongoStore(settings)
    await store.connect()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["store"] = store
    dispatcher["settings"] = settings
    dispatcher.include_router(start.router)
    dispatcher.include_router(user.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(broadcast.router)

    try:
        await register_bot_commands(bot, settings, store)
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
        await store.close()


def main() -> None:
    asyncio.run(run())