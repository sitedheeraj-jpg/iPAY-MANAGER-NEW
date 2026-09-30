import asyncio

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage

import app.utils.broadcast as broadcast_module
from app.utils.broadcast import BATCH_SIZE, BroadcastResult, send_broadcast


def _method() -> SendMessage:
    return SendMessage(chat_id=1, text="x")


class FakeBot:
    """Records copy_message calls; behaviour per chat is set via `plan`."""

    def __init__(self, plan: dict | None = None) -> None:
        self.plan = plan or {}
        self.calls: list[tuple[int, int, int]] = []
        self.attempts: dict[int, int] = {}

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int):
        self.calls.append((chat_id, from_chat_id, message_id))
        self.attempts[chat_id] = self.attempts.get(chat_id, 0) + 1
        behaviour = self.plan.get(chat_id)
        if callable(behaviour):
            behaviour = behaviour(self.attempts[chat_id])
        if isinstance(behaviour, Exception):
            raise behaviour
        return object()


def _fast(monkeypatch) -> None:
    """Remove the inter-batch pause so tests run instantly."""
    monkeypatch.setattr(broadcast_module, "BATCH_INTERVAL", 0)


def test_all_recipients_receive_the_admin_message(monkeypatch) -> None:
    _fast(monkeypatch)
    bot = FakeBot()
    result = asyncio.run(send_broadcast(bot, [11, 22, 33], 999, 42))

    assert (result.sent, result.blocked, result.failed) == (3, 0, 0)
    assert result.stopped is False
    assert sorted(bot.calls) == [(11, 999, 42), (22, 999, 42), (33, 999, 42)]


def test_blocked_users_and_errors_are_counted_without_stopping_the_run(monkeypatch) -> None:
    _fast(monkeypatch)
    bot = FakeBot(
        {
            2: TelegramForbiddenError(method=_method(), message="bot was blocked"),
            3: TelegramBadRequest(method=_method(), message="chat not found"),
            4: TelegramBadRequest(method=_method(), message="message is too long"),
            5: RuntimeError("boom"),
        }
    )
    result = asyncio.run(send_broadcast(bot, [1, 2, 3, 4, 5, 6], 999, 42))

    assert result.sent == 2  # users 1 and 6
    assert result.blocked == 2  # users 2 and 3
    assert result.failed == 2  # users 4 and 5
    assert result.processed == 6


def test_flood_control_waits_and_retries_the_same_user(monkeypatch) -> None:
    _fast(monkeypatch)
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float, *args, **kwargs):
        sleeps.append(delay)
        await real_sleep(0)

    def flood_once(attempt: int):
        if attempt == 1:
            return TelegramRetryAfter(
                method=_method(), message="Flood control", retry_after=3
            )
        return None

    bot = FakeBot({7: flood_once})
    monkeypatch.setattr(broadcast_module.asyncio, "sleep", fake_sleep)
    result = asyncio.run(send_broadcast(bot, [7], 999, 42))

    assert result.sent == 1
    assert bot.attempts[7] == 2
    assert sleeps and sleeps[0] >= 3


def test_large_audience_is_sent_in_batches_with_progress_updates(monkeypatch) -> None:
    _fast(monkeypatch)
    recipients = list(range(1, BATCH_SIZE * 2 + 6))
    bot = FakeBot()
    seen: list[int] = []

    async def on_progress(result: BroadcastResult, total: int) -> None:
        assert total == len(recipients)
        seen.append(result.processed)

    result = asyncio.run(
        send_broadcast(bot, recipients, 999, 42, on_progress=on_progress)
    )

    assert result.sent == len(recipients)
    assert seen == [BATCH_SIZE, BATCH_SIZE * 2, len(recipients)]


def test_stop_event_halts_after_the_current_batch(monkeypatch) -> None:
    _fast(monkeypatch)
    recipients = list(range(1, BATCH_SIZE * 3 + 1))
    bot = FakeBot()
    stop = asyncio.Event()

    async def on_progress(result: BroadcastResult, total: int) -> None:
        stop.set()

    result = asyncio.run(
        send_broadcast(
            bot, recipients, 999, 42, stop_event=stop, on_progress=on_progress
        )
    )

    assert result.stopped is True
    assert result.sent == BATCH_SIZE
    assert len(bot.calls) == BATCH_SIZE


def test_empty_audience_sends_nothing(monkeypatch) -> None:
    _fast(monkeypatch)
    bot = FakeBot()
    result = asyncio.run(send_broadcast(bot, [], 999, 42))

    assert result.processed == 0
    assert bot.calls == []
