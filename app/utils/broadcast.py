"""Delivery engine for admin broadcasts.

Messages are sent with ``copy_message`` so the exact text (with its formatting)
or photo (with its caption) that the admin composed is what recipients see,
without a "Forwarded from" header.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

logger = logging.getLogger(__name__)

# Telegram allows roughly 30 messages per second for a bot. Stay below that.
BATCH_SIZE = 25
BATCH_INTERVAL = 1.0
MAX_ATTEMPTS = 3

Outcome = Literal["sent", "blocked", "failed"]


@dataclass
class BroadcastResult:
    sent: int = 0
    blocked: int = 0
    failed: int = 0
    stopped: bool = False

    @property
    def processed(self) -> int:
        return self.sent + self.blocked + self.failed


ProgressCallback = Callable[[BroadcastResult, int], Awaitable[None]]


async def copy_to_chat(
    bot: Bot, chat_id: int, from_chat_id: int, message_id: int
) -> Outcome:
    """Copy one message to one chat and classify the result."""
    for _ in range(MAX_ATTEMPTS):
        try:
            await bot.copy_message(
                chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id
            )
            return "sent"
        except TelegramRetryAfter as exc:
            # Telegram asked us to slow down; wait as instructed and retry.
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError:
            # User blocked the bot, deactivated their account, or left.
            return "blocked"
        except TelegramBadRequest as exc:
            if "chat not found" in str(exc).lower():
                return "blocked"
            logger.warning("Broadcast to %s rejected: %s", chat_id, exc)
            return "failed"
        except Exception:
            logger.exception("Broadcast to %s failed unexpectedly", chat_id)
            return "failed"
    return "failed"


async def send_broadcast(
    bot: Bot,
    recipient_ids: Sequence[int],
    from_chat_id: int,
    message_id: int,
    stop_event: asyncio.Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> BroadcastResult:
    """Send one message to every recipient in rate-limited batches."""
    result = BroadcastResult()
    total = len(recipient_ids)
    loop = asyncio.get_running_loop()

    for start in range(0, total, BATCH_SIZE):
        if stop_event is not None and stop_event.is_set():
            result.stopped = True
            break

        batch = recipient_ids[start : start + BATCH_SIZE]
        batch_started = loop.time()
        outcomes = await asyncio.gather(
            *(copy_to_chat(bot, chat_id, from_chat_id, message_id) for chat_id in batch)
        )
        for outcome in outcomes:
            if outcome == "sent":
                result.sent += 1
            elif outcome == "blocked":
                result.blocked += 1
            else:
                result.failed += 1

        if on_progress is not None:
            await on_progress(result, total)

        remaining = BATCH_INTERVAL - (loop.time() - batch_started)
        if remaining > 0 and start + BATCH_SIZE < total:
            await asyncio.sleep(remaining)

    return result
