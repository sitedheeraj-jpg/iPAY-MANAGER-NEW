import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def send_message_with_effect(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    effect_id: str | None = None,
    **kwargs: Any,
) -> Message:
    """Send with a Telegram message effect, retrying without it if invalid."""
    if effect_id is None:
        return await bot.send_message(chat_id, text, **kwargs)

    try:
        return await bot.send_message(
            chat_id,
            text,
            message_effect_id=effect_id,
            **kwargs,
        )
    except TelegramBadRequest as exc:
        if "EFFECT_ID_INVALID" not in str(exc):
            raise
        logger.warning(
            "Telegram rejected a message effect; retrying the message without it."
        )
        return await bot.send_message(chat_id, text, **kwargs)