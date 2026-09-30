import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from app.config import Settings
from app.database import MongoStore

logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand(command="start", description="Register or open dashboard"),
    BotCommand(command="menu", description="Open main dashboard"),
    BotCommand(command="profile", description="View your profile"),
    BotCommand(command="balance", description="View wallet balance"),
    BotCommand(command="history", description="View balance history"),
    BotCommand(command="withdraw", description="Request a withdrawal"),
    BotCommand(command="submit_task", description="Submit task proof"),
    BotCommand(command="my_tasks", description="View submitted tasks"),
    BotCommand(command="add_team", description="Add team member (agents)"),
    BotCommand(command="team", description="View team (agents)"),
    BotCommand(command="id", description="Show your Telegram ID"),
    BotCommand(command="help", description="Show help and commands"),
    BotCommand(command="cancel", description="Cancel current form"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Open admin panel"),
    BotCommand(command="users", description="Manage all users"),
    BotCommand(command="admins", description="Manage admins (owners)"),
    BotCommand(command="broadcast", description="Send message/photo to members"),
]


async def register_bot_commands(
    bot: Bot, settings: Settings, store: MongoStore | None = None
) -> None:
    """Register the command menu automatically on every deployment."""
    await bot.set_my_commands(
        USER_COMMANDS, scope=BotCommandScopeAllPrivateChats()
    )
    admin_ids = (
        await store.list_admin_ids() if store is not None else settings.owner_ids
    )
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as exc:
            logger.warning("Could not register admin commands for %s: %s", admin_id, exc)