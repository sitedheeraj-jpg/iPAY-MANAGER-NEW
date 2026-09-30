from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import MongoStore
from app.handlers.deps import is_approved, notify_admins
from app.handlers.states import RegistrationStates
from app.keyboards import dashboard_keyboard
from app.keyboards.admin import approval_keyboard
from app.keyboards.registration import (
    registration_prompt_keyboard,
    registration_rejected_keyboard,
)
from app.utils.effects import HEART, THUMBS_DOWN
from app.utils.formatting import dashboard_text
from app.utils.telegram_messaging import send_message_with_effect

router = Router(name="start")
IPAY_REGISTRATION_REJECTED_TEXT = (
    "❌ <b>Registration Rejected!</b>\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "<blockquote>You are not registered through the authorised iPAY link.</blockquote>\n"
    "Register here now 👇"
)
REGISTRATION_PROMPT_TEXT = (
    "🚀 <b>Welcome to iPAY Bot</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "Send Your iPAY User ID.\n\n"
    "<blockquote expandable>"
    "✅ UID must be 3–32 characters\n"
    "✅ Every UID can be used only once"
    "</blockquote>\n"
    "<blockquote>Not registered yet? Register here 👇</blockquote>"
)


async def show_dashboard(message: Message, user: dict) -> None:
    await message.answer(
        dashboard_text(user, message.from_user.full_name),
        reply_markup=dashboard_keyboard(user["role"] == "Agent"),
    )


@router.message(CommandStart())
async def command_start(
    message: Message, state: FSMContext, store: MongoStore, bot
) -> None:
    user = await store.get_user(message.from_user.id)
    if is_approved(user):
        await show_dashboard(message, user)
        return
    if user and str(user.get("status", "")).casefold() == "pending":
        await message.answer(
            "⏳ <b>Registration under review</b>\n\n"
            "Your UID is already submitted and is waiting for admin approval.\n"
            "You will receive a Telegram notification as soon as it is processed."
        )
        return

    await state.set_state(RegistrationStates.custom_uid)
    prompt = await send_message_with_effect(
        bot,
        message.chat.id,
        REGISTRATION_PROMPT_TEXT,
        effect_id=HEART,
        reply_markup=registration_prompt_keyboard(),
    )
    await state.update_data(
        registration_prompt_chat_id=prompt.chat.id,
        registration_prompt_message_id=prompt.message_id,
    )


@router.callback_query(F.data == "registration:retry")
async def retry_registration(
    query: CallbackQuery, state: FSMContext, store: MongoStore
) -> None:
    user = await store.get_user(query.from_user.id)
    status = str(user.get("status", "")).casefold() if user else ""
    if status == "pending":
        await query.answer("Your registration is already under review.", show_alert=True)
        return
    if status == "approved":
        await query.answer("Your account is already approved.", show_alert=True)
        return
    await state.clear()
    await state.set_state(RegistrationStates.custom_uid)
    await query.message.edit_text(
        REGISTRATION_PROMPT_TEXT,
        reply_markup=registration_prompt_keyboard(),
    )
    await state.update_data(
        registration_prompt_chat_id=query.message.chat.id,
        registration_prompt_message_id=query.message.message_id,
    )
    await query.answer("Send your iPAY User ID here.")


@router.message(RegistrationStates.custom_uid)
async def receive_custom_uid(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    bot,
    settings: Settings,
) -> None:
    custom_uid = (message.text or "").strip()
    if not 3 <= len(custom_uid) <= 32 or not all(
        char.isalnum() or char in "._-" for char in custom_uid
    ):
        await message.answer(
            "Invalid UID. Use 3–32 letters, numbers, dots, dashes, or underscores."
        )
        return
    try:
        user = await store.register_user(message.from_user.id, custom_uid)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    state_data = await state.get_data()
    await state.clear()
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    if is_approved(user):
        await show_dashboard(message, user)
        return

    submitted_text = (
        "✅ <b>Registration submitted!</b>\n\n"
        f"UID: <code>{escape(custom_uid)}</code>\n"
        "Your account is locked until an administrator reviews it.\n"
        "You will receive the approval decision here in Telegram."
    )
    prompt_chat_id = state_data.get("registration_prompt_chat_id")
    prompt_message_id = state_data.get("registration_prompt_message_id")
    if prompt_chat_id and prompt_message_id:
        try:
            await bot.edit_message_text(
                chat_id=prompt_chat_id,
                message_id=prompt_message_id,
                text=submitted_text,
                reply_markup=None,
            )
        except Exception:
            await bot.send_message(message.chat.id, submitted_text)
    else:
        await bot.send_message(message.chat.id, submitted_text)
    await notify_admins(
        bot,
        settings,
        f"🆕 <b>New user registration</b>\n\n"
        f"UID: <code>{escape(custom_uid)}</code>\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Name: {escape(message.from_user.full_name)}",
        approval_keyboard("user", str(message.from_user.id)),
        store=store,
        notification_key=f"user:{message.from_user.id}",
    )


async def notify_registration_rejected(bot, telegram_id: int) -> None:
    await send_message_with_effect(
        bot,
        telegram_id,
        IPAY_REGISTRATION_REJECTED_TEXT,
        effect_id=THUMBS_DOWN,
        reply_markup=registration_rejected_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled. Send /start to open the bot.")


@router.callback_query(F.data == "common:cancel")
async def cancel_callback(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Cancelled")
    await query.message.edit_text("Cancelled. Send /start to open the bot.")