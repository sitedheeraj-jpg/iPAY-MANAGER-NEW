import asyncio
import logging
import time
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import MongoStore
from app.handlers.deps import is_admin
from app.handlers.states import BroadcastStates
from app.keyboards import cancel_keyboard
from app.keyboards.admin import (
    broadcast_audience_keyboard,
    broadcast_confirm_keyboard,
    broadcast_progress_keyboard,
)
from app.utils.broadcast import BroadcastResult, send_broadcast

logger = logging.getLogger(__name__)
router = Router(name="broadcast")

AUDIENCE_LABELS = {
    "approved": "Approved users",
    "agents": "Agents only",
    "users": "Regular users only",
    "all": "Everyone who started the bot",
}

# Only one broadcast may run at a time; the event lets an admin stop it.
ACTIVE_BROADCASTS: dict[str, asyncio.Event] = {}
# Strong references so running broadcast tasks are never garbage collected.
_background_tasks: set[asyncio.Task] = set()

PROGRESS_EDIT_INTERVAL = 3.0


def admin_only(query_or_message, settings: Settings, store: MongoStore) -> bool:
    return is_admin(query_or_message.from_user.id, settings, store)


async def audience_screen(store: MongoStore) -> tuple[str, object]:
    counts = {
        key: await store.count_broadcast_recipients(key) for key in AUDIENCE_LABELS
    }
    text = (
        "📢 <b>Broadcast</b>\n\n"
        "Send a message or photo to your members.\n"
        "Choose who should receive it:"
    )
    return text, broadcast_audience_keyboard(counts)


def progress_text(
    audience: str, result: BroadcastResult, total: int, *, finished: bool = False
) -> str:
    if finished:
        title = "⛔ <b>Broadcast stopped</b>" if result.stopped else (
            "✅ <b>Broadcast complete</b>"
        )
    else:
        title = "📤 <b>Broadcasting…</b>"
    return (
        f"{title}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Audience: <b>{AUDIENCE_LABELS.get(audience, audience)}</b>\n"
        f"Progress: <b>{result.processed}/{total}</b>\n"
        f"✅ Delivered: <b>{result.sent}</b>\n"
        f"🚫 Blocked / unreachable: <b>{result.blocked}</b>\n"
        f"⚠️ Failed: <b>{result.failed}</b>"
    )


@router.message(Command("broadcast"))
async def open_broadcast_command(
    message: Message, state: FSMContext, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(message, settings, store):
        await message.answer("You are not authorized to send broadcasts.")
        return
    await state.clear()
    text, keyboard = await audience_screen(store)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin:broadcast")
async def open_broadcast_menu(
    query: CallbackQuery, state: FSMContext, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    await state.clear()
    text, keyboard = await audience_screen(store)
    await query.answer()
    await query.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("bc:aud:"))
async def choose_audience(
    query: CallbackQuery, state: FSMContext, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    audience = query.data.rsplit(":", 1)[1]
    if audience not in AUDIENCE_LABELS:
        await query.answer("Unknown audience.", show_alert=True)
        return
    if ACTIVE_BROADCASTS:
        await query.answer(
            "A broadcast is already running. Wait for it to finish or stop it.",
            show_alert=True,
        )
        return
    total = await store.count_broadcast_recipients(audience)
    if total == 0:
        await query.answer("There are no recipients in this audience.", show_alert=True)
        return
    await state.clear()
    await state.set_state(BroadcastStates.content)
    await state.update_data(audience=audience)
    await query.answer()
    await query.message.edit_text(
        f"📢 <b>Broadcast to: {AUDIENCE_LABELS[audience]}</b> ({total})\n\n"
        "Now send the <b>message</b> or a single <b>photo</b> (with an optional "
        "caption) exactly as you want members to see it.\n"
        "Text formatting such as bold, italic and links is kept.",
        reply_markup=cancel_keyboard(),
    )


@router.message(BroadcastStates.content)
async def receive_broadcast_content(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
    bot: Bot,
) -> None:
    if not admin_only(message, settings, store):
        await state.clear()
        return

    if message.photo:
        content_type = "photo"
    elif message.text:
        if message.text.startswith("/"):
            await message.answer(
                "That looks like a command. Send the broadcast message itself, "
                "or /cancel to abort.",
                reply_markup=cancel_keyboard(),
            )
            return
        content_type = "text"
    else:
        await message.answer(
            "Only text messages and photos can be broadcast. "
            "Please send text or a photo.",
            reply_markup=cancel_keyboard(),
        )
        return

    data = await state.get_data()
    audience = data.get("audience")
    if audience not in AUDIENCE_LABELS:
        await state.clear()
        await message.answer("Session expired. Open /broadcast again.")
        return
    total = await store.count_broadcast_recipients(audience)

    await state.update_data(
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        content_type=content_type,
    )
    await state.set_state(BroadcastStates.confirm)

    # Show the admin exactly what recipients will receive.
    await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await message.answer(
        "👆 <b>Preview</b> — this is exactly what members will receive.\n\n"
        f"Audience: <b>{AUDIENCE_LABELS[audience]}</b>\n"
        f"Recipients: <b>{total}</b>\n\n"
        "Send it now?",
        reply_markup=broadcast_confirm_keyboard(total),
    )


@router.callback_query(BroadcastStates.confirm, F.data == "bc:send")
async def confirm_broadcast(
    query: CallbackQuery,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
    bot: Bot,
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        await state.clear()
        return
    if ACTIVE_BROADCASTS:
        await query.answer(
            "A broadcast is already running. Wait for it to finish or stop it.",
            show_alert=True,
        )
        return

    data = await state.get_data()
    audience = data.get("audience")
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    content_type = data.get("content_type", "text")
    if audience not in AUDIENCE_LABELS or source_message_id is None:
        await state.clear()
        await query.answer("Session expired. Open /broadcast again.", show_alert=True)
        return

    recipient_ids = await store.list_broadcast_recipient_ids(audience)
    if not recipient_ids:
        await state.clear()
        await query.answer("There are no recipients in this audience.", show_alert=True)
        return

    await state.clear()
    broadcast_id = uuid4().hex[:12]
    stop_event = asyncio.Event()
    ACTIVE_BROADCASTS[broadcast_id] = stop_event
    await store.create_broadcast(
        broadcast_id,
        query.from_user.id,
        audience,
        content_type,
        len(recipient_ids),
    )
    await query.answer("Broadcast started")
    progress_message = await query.message.edit_text(
        progress_text(audience, BroadcastResult(), len(recipient_ids)),
        reply_markup=broadcast_progress_keyboard(broadcast_id),
    )

    task = asyncio.create_task(
        run_broadcast(
            bot=bot,
            store=store,
            broadcast_id=broadcast_id,
            audience=audience,
            recipient_ids=recipient_ids,
            source_chat_id=int(source_chat_id),
            source_message_id=int(source_message_id),
            stop_event=stop_event,
            progress_message=progress_message,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def run_broadcast(
    *,
    bot: Bot,
    store: MongoStore,
    broadcast_id: str,
    audience: str,
    recipient_ids: list[int],
    source_chat_id: int,
    source_message_id: int,
    stop_event: asyncio.Event,
    progress_message: Message,
) -> None:
    """Send the broadcast in the background and keep the admin informed."""
    total = len(recipient_ids)
    last_edit = 0.0

    async def on_progress(result: BroadcastResult, _total: int) -> None:
        nonlocal last_edit
        now = time.monotonic()
        if now - last_edit < PROGRESS_EDIT_INTERVAL:
            return
        last_edit = now
        try:
            await progress_message.edit_text(
                progress_text(audience, result, total),
                reply_markup=broadcast_progress_keyboard(broadcast_id),
            )
        except TelegramBadRequest:
            pass  # "message is not modified" or message deleted

    result = BroadcastResult()
    status = "Completed"
    try:
        result = await send_broadcast(
            bot,
            recipient_ids,
            source_chat_id,
            source_message_id,
            stop_event=stop_event,
            on_progress=on_progress,
        )
        if result.stopped:
            status = "Stopped"
    except Exception:
        logger.exception("Broadcast %s crashed", broadcast_id)
        status = "Failed"
    finally:
        ACTIVE_BROADCASTS.pop(broadcast_id, None)

    try:
        await store.finish_broadcast(
            broadcast_id, status, result.sent, result.blocked, result.failed
        )
    except Exception:
        logger.exception("Could not save broadcast %s result", broadcast_id)

    summary = progress_text(audience, result, total, finished=True)
    if status == "Failed":
        summary = "❌ <b>Broadcast failed</b> — see logs.\n\n" + summary
    try:
        await progress_message.edit_text(summary, reply_markup=None)
    except TelegramBadRequest:
        try:
            await bot.send_message(progress_message.chat.id, summary)
        except Exception:
            pass


@router.callback_query(F.data.startswith("bc:stop:"))
async def stop_broadcast(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    broadcast_id = query.data.rsplit(":", 1)[1]
    event = ACTIVE_BROADCASTS.get(broadcast_id)
    if event is None:
        await query.answer("This broadcast has already finished.", show_alert=True)
        return
    event.set()
    await query.answer("Stopping after the current batch…", show_alert=True)
