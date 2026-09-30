from html import escape
from math import isfinite

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import MongoStore
from app.handlers.deps import (
    is_approved,
    notify_admins,
    sync_admin_notifications,
)
from app.handlers.states import (
    TaskSubmissionStates,
    TeamAdditionStates,
    WithdrawalStates,
)
from app.keyboards import cancel_keyboard
from app.keyboards.admin import approval_keyboard
from app.keyboards.user import (
    back_to_menu_keyboard,
    dashboard_keyboard,
    finish_proof_keyboard,
)
from app.models import TransactionType
from app.utils.effects import STARSTRUCK
from app.utils.formatting import (
    HELP_TEXT,
    dashboard_text,
    money,
    profile_text,
    task_history_text,
    team_text,
    transaction_history_text,
)
from app.utils.telegram_messaging import send_message_with_effect

router = Router(name="user")


async def approved_user(
    message: Message, store: MongoStore, telegram_id: int | None = None
) -> dict | None:
    """Resolve approval for the person who triggered the action.

    On a callback query, message.from_user is the bot that sent the
    dashboard message, not the user who clicked its button.
    """
    actor_id = telegram_id if telegram_id is not None else message.from_user.id
    user = await store.get_user(actor_id)
    if not is_approved(user):
        await message.answer(
            "🔒 <b>Account locked</b>\n\n"
            "Your account must be approved before you can use wallet features.\n"
            "Send /start to check your registration status."
        )
        return None
    return user


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=back_to_menu_keyboard())


@router.message(Command("id"))
async def id_command(message: Message) -> None:
    await message.answer(
        f"🪪 Your Telegram ID is:\n<code>{message.from_user.id}</code>\n\n"
        "Agents can use this ID when submitting a team member."
    )


@router.message(Command("menu"))
async def menu_command(message: Message, store: MongoStore) -> None:
    user = await approved_user(message, store)
    if user:
        await message.answer(
            dashboard_text(user, message.from_user.full_name),
            reply_markup=dashboard_keyboard(user["role"] == "Agent"),
        )


@router.message(Command("profile"))
async def profile_command(message: Message, store: MongoStore) -> None:
    user = await store.get_user(message.from_user.id)
    if not user:
        await message.answer("You are not registered yet. Send /start to begin.")
        return
    await message.answer(
        profile_text(user, message.from_user.full_name),
        reply_markup=back_to_menu_keyboard(),
    )


@router.message(Command("balance"))
async def balance_command(message: Message, store: MongoStore) -> None:
    user = await approved_user(message, store)
    if user:
        await message.answer(
            f"💰 <b>Wallet Balance</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Available balance: <b>{money(user['balance'])}</b>",
            reply_markup=back_to_menu_keyboard(),
        )


@router.message(Command("history"))
async def history_command(message: Message, store: MongoStore) -> None:
    user = await approved_user(message, store)
    if user:
        await message.answer(
            transaction_history_text(
                await store.list_transactions(message.from_user.id)
            ),
            reply_markup=back_to_menu_keyboard(),
        )


@router.message(Command("withdraw"))
async def withdraw_command(
    message: Message, state: FSMContext, store: MongoStore
) -> None:
    user = await approved_user(message, store)
    if user:
        await state.set_state(WithdrawalStates.amount)
        await message.answer(
            f"💸 <b>New Withdrawal</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Available balance: <b>{money(user['balance'])}</b>\n\n"
            "Send the amount you want to withdraw.",
            reply_markup=cancel_keyboard(),
        )


@router.message(Command("add_team"))
async def add_team_command(
    message: Message, state: FSMContext, store: MongoStore
) -> None:
    user = await approved_user(message, store)
    if not user:
        return
    if user["role"] != "Agent":
        await message.answer("👥 Only approved Agent accounts can add team members.")
        return
    await state.set_state(TeamAdditionStates.custom_uid)
    await message.answer(
        "👥 <b>Add Team Member</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Send the member's unique custom UID.\n"
        "The member will be created only after admin approval.",
        reply_markup=cancel_keyboard(),
    )


async def begin_task_submission(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    telegram_id: int | None = None,
) -> None:
    user = await approved_user(message, store, telegram_id)
    if not user:
        return
    await state.clear()
    await state.set_state(TaskSubmissionStates.description)
    await message.answer(
        "🧾 <b>Submit Task</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Send the task name or a clear description of what you completed.\n\n"
        "Example: <i>Completed daily app promotion task for 10 users.</i>",
        reply_markup=cancel_keyboard(),
    )


@router.message(Command("submit_task"))
async def submit_task_command(
    message: Message, state: FSMContext, store: MongoStore
) -> None:
    await begin_task_submission(message, state, store)


@router.message(Command("my_tasks"))
async def my_tasks_command(message: Message, store: MongoStore) -> None:
    user = await approved_user(message, store)
    if user:
        await message.answer(
            task_history_text(await store.list_user_tasks(message.from_user.id)),
            reply_markup=back_to_menu_keyboard(),
        )


@router.message(TaskSubmissionStates.description)
async def task_description(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if not 5 <= len(description) <= 1000:
        await message.answer("Please send a task description between 5 and 1000 characters.")
        return
    await state.update_data(description=description, proof_file_ids=[])
    await state.set_state(TaskSubmissionStates.proof)
    await message.answer(
        "📸 <b>Upload proof screenshots</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Send one or more screenshots of your completed task.\n"
        "After sending all screenshots, press <b>Submit Proof to Admin</b>.",
        reply_markup=finish_proof_keyboard(),
    )


@router.message(TaskSubmissionStates.proof, F.photo)
async def task_proof_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    proof_file_ids = list(data.get("proof_file_ids", []))
    proof_file_ids.append(message.photo[-1].file_id)
    await state.update_data(proof_file_ids=proof_file_ids)
    await message.answer(
        f"✅ Screenshot {len(proof_file_ids)} received. "
        "Send another or press <b>Submit Proof to Admin</b>.",
        reply_markup=finish_proof_keyboard(),
    )


@router.message(TaskSubmissionStates.proof)
async def task_proof_invalid(message: Message) -> None:
    await message.answer(
        "Please upload a screenshot image. When finished, press "
        "<b>Submit Proof to Admin</b>.",
        reply_markup=finish_proof_keyboard(),
    )


@router.callback_query(F.data == "user:submit_task")
async def submit_task_callback(
    query: CallbackQuery, state: FSMContext, store: MongoStore
) -> None:
    await query.answer()
    await begin_task_submission(query.message, state, store, query.from_user.id)


@router.callback_query(F.data == "user:my_tasks")
async def my_tasks_callback(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user):
        await query.message.edit_text("Your account is not approved yet.")
        return
    await query.message.edit_text(
        task_history_text(await store.list_user_tasks(query.from_user.id)),
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "task:finish_proof")
async def finish_task_submission(
    query: CallbackQuery,
    state: FSMContext,
    store: MongoStore,
    bot,
    settings: Settings,
) -> None:
    user = await store.get_user(query.from_user.id)
    if not is_approved(user):
        await query.answer("Your account is not approved.", show_alert=True)
        await state.clear()
        return
    if await state.get_state() != TaskSubmissionStates.proof.state:
        await query.answer("This task form is no longer active.", show_alert=True)
        return
    data = await state.get_data()
    proof_file_ids = list(data.get("proof_file_ids", []))
    if not proof_file_ids:
        await query.answer("Upload at least one screenshot first.", show_alert=True)
        return
    task = await store.create_task_submission(
        query.from_user.id, data["description"], proof_file_ids
    )
    await state.clear()
    await query.answer("Task submitted for review.")
    try:
        await query.message.delete()
    except Exception:
        pass
    await send_message_with_effect(
        bot,
        query.from_user.id,
        "🥰 <b>Task submitted successfully!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Task ID: <code>{task['task_id'][:8]}</code>\n"
        f"Proof files: <b>{len(proof_file_ids)}</b>\n\n"
        "Your submission is with the iPAY review team. "
        "We’ll notify you when it’s reviewed.",
        effect_id=STARSTRUCK,
    )
    review_text = (
        "🧾 <b>New Task Submission</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Task ID: <code>{task['task_id']}</code>\n"
        f"User: <code>{task['user_id']}</code>\n"
        f"Description:\n{escape(task['description'])}\n"
        f"Proof screenshots: <b>{len(proof_file_ids)}</b>"
    )
    review_markup = approval_keyboard("task", task["task_id"])
    await notify_admins(
        bot,
        settings,
        review_text,
        review_markup,
        store=store,
        notification_key=f"task:{task['task_id']}",
    )
    for admin_id in await store.list_admin_ids():
        for index, file_id in enumerate(proof_file_ids, start=1):
            try:
                sent = await bot.send_photo(
                    admin_id,
                    file_id,
                    caption=(
                        f"📸 Task {task['task_id'][:8]} proof "
                        f"{index}/{len(proof_file_ids)}"
                    ),
                    reply_markup=review_markup if index == len(proof_file_ids) else None,
                )
                await store.record_admin_notification(
                    f"task:{task['task_id']}",
                    admin_id,
                    sent.message_id,
                    "photo",
                    sent.caption or "",
                )
            except Exception:
                continue
@router.message(Command("team"))
async def team_command(message: Message, store: MongoStore) -> None:
    user = await approved_user(message, store)
    if not user:
        return
    if user["role"] != "Agent":
        await message.answer("👥 Only approved Agent accounts have a team.")
        return
    await message.answer(
        team_text(await store.list_agent_members(message.from_user.id)),
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "user:menu")
async def user_menu(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user):
        await query.message.edit_text("Your account is not approved yet.")
        return
    await query.message.edit_text(
        dashboard_text(user, query.from_user.full_name),
        reply_markup=dashboard_keyboard(user["role"] == "Agent"),
    )


@router.callback_query(F.data == "user:profile")
async def profile_callback(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not user:
        await query.message.edit_text("You are not registered yet. Send /start to begin.")
        return
    await query.message.edit_text(
        profile_text(user, query.from_user.full_name),
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "user:help")
async def help_callback(query: CallbackQuery) -> None:
    await query.answer()
    await query.message.edit_text(HELP_TEXT, reply_markup=back_to_menu_keyboard())


@router.callback_query(F.data == "user:team")
async def team_callback(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user) or user["role"] != "Agent":
        await query.message.edit_text("Only approved Agent accounts have a team.")
        return
    await query.message.edit_text(
        team_text(await store.list_agent_members(query.from_user.id)),
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "user:balance")
async def balance(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user):
        await query.message.edit_text("Your account is not approved yet.")
        return
    await query.message.edit_text(
        f"💰 <b>Wallet Balance</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Available balance: <b>{money(user['balance'])}</b>",
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "user:history")
async def history(query: CallbackQuery, store: MongoStore) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user):
        await query.message.edit_text("Your account is not approved yet.")
        return
    await query.message.edit_text(
        transaction_history_text(await store.list_transactions(query.from_user.id)),
        reply_markup=back_to_menu_keyboard(),
    )


@router.callback_query(F.data == "user:withdraw")
async def start_withdrawal(
    query: CallbackQuery, state: FSMContext, store: MongoStore
) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user):
        await query.message.edit_text("Your account is not approved yet.")
        return
    await state.set_state(WithdrawalStates.amount)
    await query.message.edit_text(
        f"💸 <b>New Withdrawal</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Available balance: <b>{money(user['balance'])}</b>\n\n"
        "Send the amount you want to withdraw.",
        reply_markup=cancel_keyboard(),
    )


@router.message(WithdrawalStates.amount)
async def withdrawal_amount(message: Message, state: FSMContext, store: MongoStore) -> None:
    try:
        amount = round(float((message.text or "").strip()), 2)
    except ValueError:
        await message.answer("Send a valid amount, for example: 500")
        return
    user = await store.get_user(message.from_user.id)
    if not isfinite(amount) or amount <= 0:
        await message.answer("Amount must be greater than zero.")
        return
    if not user or user["balance"] < amount:
        await message.answer("That amount is higher than your available balance.")
        return
    await state.update_data(amount=amount)
    await state.set_state(WithdrawalStates.payment_method)
    await message.answer(
        "💳 <b>Payment Details</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Send your UPI ID as text, or upload your UPI QR image.\n"
        "This information will be visible to the admin processing your request.",
        reply_markup=cancel_keyboard(),
    )


@router.message(WithdrawalStates.payment_method)
async def withdrawal_payment_method(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    bot,
    settings: Settings,
) -> None:
    payment_photo_file_id = None
    if message.photo:
        payment_method = "UPI QR image"
        payment_photo_file_id = message.photo[-1].file_id
    else:
        payment_method = (message.text or "").strip()
        if not payment_method or len(payment_method) > 300:
            await message.answer(
                "Send a UPI ID as text or upload one QR image (max 300 characters for text)."
            )
            return
    data = await state.get_data()
    withdrawal = await store.create_withdrawal(
        message.from_user.id,
        float(data["amount"]),
        payment_method,
        payment_photo_file_id,
    )
    await state.clear()
    await message.answer(
        f"✅ Withdrawal request submitted for ₹{withdrawal['amount']:.2f}.\n"
        "Funds remain available until an admin approves the request."
    )
    await notify_admins(
        bot,
        settings,
        f"💸 <b>New Withdrawal Request</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"User: <code>{message.from_user.id}</code>\n"
        f"Amount: <b>₹{withdrawal['amount']:.2f}</b>\n"
        f"Payment: <code>{escape(payment_method)}</code>",
        approval_keyboard("withdrawal", withdrawal["withdrawal_id"]),
        store=store,
        notification_key=f"withdrawal:{withdrawal['withdrawal_id']}",
    )
    if payment_photo_file_id:
        for admin_id in await store.list_admin_ids():
            try:
                sent = await bot.send_photo(
                    admin_id,
                    payment_photo_file_id,
                    caption=(
                        f"🧾 QR image for withdrawal "
                        f"<code>{withdrawal['withdrawal_id']}</code>"
                    ),
                    reply_markup=approval_keyboard(
                        "withdrawal", withdrawal["withdrawal_id"]
                    ),
                )
                await store.record_admin_notification(
                    f"withdrawal:{withdrawal['withdrawal_id']}",
                    admin_id,
                    sent.message_id,
                    "photo",
                    sent.caption or "",
                )
            except Exception:
                continue


@router.callback_query(F.data == "user:add_team")
async def start_team_addition(
    query: CallbackQuery, state: FSMContext, store: MongoStore
) -> None:
    user = await store.get_user(query.from_user.id)
    await query.answer()
    if not is_approved(user) or user["role"] != "Agent":
        await query.message.edit_text("Only approved agents can add team members.")
        return
    await state.set_state(TeamAdditionStates.custom_uid)
    await query.message.edit_text(
        "👥 Send the new member's unique custom UID.",
        reply_markup=cancel_keyboard(),
    )


@router.message(TeamAdditionStates.custom_uid)
async def team_custom_uid(message: Message, state: FSMContext) -> None:
    custom_uid = (message.text or "").strip()
    if not 3 <= len(custom_uid) <= 32 or not all(
        char.isalnum() or char in "._-" for char in custom_uid
    ):
        await message.answer("Use a valid UID: 3–32 letters, numbers, dots, dashes, or underscores.")
        return
    await state.update_data(custom_uid=custom_uid)
    await state.set_state(TeamAdditionStates.telegram_id)
    await message.answer("Now send the member's numeric Telegram ID.")


@router.message(TeamAdditionStates.telegram_id)
async def team_telegram_id(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    bot,
    settings: Settings,
) -> None:
    raw_id = (message.text or "").strip()
    if not raw_id.isdigit():
        await message.answer("Telegram ID must contain only numbers.")
        return
    member_id = int(raw_id)
    if await store.get_user(member_id):
        await message.answer("That Telegram ID is already registered.")
        return
    data = await state.get_data()
    try:
        addition = await store.create_team_addition(
            message.from_user.id, data["custom_uid"], member_id
        )
    except Exception:
        await message.answer("That team request could not be created. Check whether the UID is already in use.")
        return
    await state.clear()
    await message.answer("✅ Team addition submitted for admin approval.")
    await notify_admins(
        bot,
        settings,
        f"👥 <b>New team addition</b>\n\n"
        f"Agent: <code>{message.from_user.id}</code>\n"
        f"Member Telegram ID: <code>{member_id}</code>\n"
        f"Member UID: <code>{escape(data['custom_uid'])}</code>",
        approval_keyboard("team", addition["addition_id"]),
        store=store,
        notification_key=f"team:{addition['addition_id']}",
    )