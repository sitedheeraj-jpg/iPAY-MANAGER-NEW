from html import escape
from math import isfinite

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database import MongoStore
from app.handlers.deps import is_admin, sync_admin_notifications
from app.handlers.start import notify_registration_rejected
from app.handlers.states import (
    AdminSearchStates,
    AdminManagementStates,
    FundAdjustmentStates,
    TaskRewardStates,
)
from app.keyboards import cancel_keyboard
from app.keyboards.admin import (
    admin_menu_keyboard,
    admin_management_keyboard,
    approval_keyboard,
    pagination_keyboard,
    user_management_keyboard,
)
from app.models import Role, Status, TransactionType, WithdrawalStatus
from app.utils.effects import FIRE, PARTY_POPPER
from app.utils.formatting import money
from app.utils.telegram_messaging import send_message_with_effect

router = Router(name="admin")
PAGE_SIZE = 5


def admin_only(
    query_or_message, settings: Settings, store: MongoStore | None = None
) -> bool:
    return is_admin(query_or_message.from_user.id, settings, store)


async def admin_menu_text(
    store: MongoStore, can_manage_admins: bool = False
) -> tuple[str, object]:
    users = await store.count_pending_users()
    teams = await store.count_pending_team_additions()
    withdrawals = await store.count_pending_withdrawals()
    tasks = await store.count_pending_tasks()
    text = (
        "🛡 <b>Admin Panel</b>\n\n"
        "Choose a queue or search for a user to manage their wallet and role."
    )
    return text, admin_menu_keyboard(
        users, teams, withdrawals, tasks, can_manage_admins=can_manage_admins
    )


@router.message(Command("admin"))
async def open_admin(message: Message, store: MongoStore, settings: Settings) -> None:
    if not admin_only(message, settings, store):
        await message.answer("You are not authorized to use the admin panel.")
        return
    text, keyboard = await admin_menu_text(store, store.is_owner(message.from_user.id))
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("users"))
async def open_all_users(message: Message, store: MongoStore, settings: Settings) -> None:
    if not admin_only(message, settings, store):
        await message.answer("You are not authorized to use the admin panel.")
        return
    await send_all_users_page(message, store, settings, 0)


@router.message(Command("admins"))
async def open_admins(
    message: Message, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(message, settings, store) or not store.is_owner(
        message.from_user.id
    ):
        await message.answer("Only owners can manage admins.")
        return
    admins = await store.list_admins()
    lines = [
        "👑 <b>Admin Management</b>",
        "━━━━━━━━━━━━━━━━━━",
        "Owners are configured with OWNER_IDS and cannot be removed here.",
        "",
    ]
    for item in admins:
        lines.append(
            f"• <b>{escape(str(item.get('role', 'Admin')))}</b> · "
            f"<code>{item['telegram_id']}</code>"
        )
    await message.answer(
        "\n".join(lines), reply_markup=admin_management_keyboard(admins)
    )


@router.callback_query(F.data == "admin:menu")
async def callback_admin_menu(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    text, keyboard = await admin_menu_text(store, store.is_owner(query.from_user.id))
    await query.answer()
    await query.message.edit_text(text, reply_markup=keyboard)


async def send_admins_page(query: CallbackQuery, store: MongoStore) -> None:
    admins = await store.list_admins()
    lines = [
        "👑 <b>Admin Management</b>",
        "━━━━━━━━━━━━━━━━━━",
        "Owners are configured with OWNER_IDS and cannot be removed here.",
        "",
    ]
    if admins:
        for item in admins:
            role = escape(str(item.get("role", "Admin")))
            lines.append(f"• <b>{role}</b> · <code>{item['telegram_id']}</code>")
    else:
        lines.append("No admins configured.")
    await query.answer()
    await query.message.edit_text(
        "\n".join(lines), reply_markup=admin_management_keyboard(admins)
    )


@router.callback_query(F.data == "admin:admins")
async def manage_admins(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store) or not store.is_owner(query.from_user.id):
        await query.answer("Only owners can manage admins.", show_alert=True)
        return
    await send_admins_page(query, store)


@router.callback_query(F.data == "admin:admins:add")
async def start_add_admin(
    query: CallbackQuery,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
) -> None:
    if not admin_only(query, settings, store) or not store.is_owner(query.from_user.id):
        await query.answer("Only owners can add admins.", show_alert=True)
        return
    await state.set_state(AdminManagementStates.telegram_id)
    await query.answer()
    await query.message.edit_text(
        "➕ <b>Add Admin</b>\n\n"
        "Send the new admin's numeric Telegram ID.\n"
        "They will receive access to the admin panel immediately.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminManagementStates.telegram_id)
async def add_admin(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
    bot,
) -> None:
    if not admin_only(message, settings, store) or not store.is_owner(
        message.from_user.id
    ):
        await state.clear()
        return
    raw_id = (message.text or "").strip()
    if not raw_id.isdigit():
        await message.answer("Telegram ID must contain only numbers.")
        return
    telegram_id = int(raw_id)
    admin, error = await store.add_admin(telegram_id, message.from_user.id)
    if error:
        await state.clear()
        await message.answer(f"⚠️ {escape(error)}")
        return
    await state.clear()
    await message.answer(
        f"✅ Admin added: <code>{telegram_id}</code>\n"
        "They can now use /admin.",
        reply_markup=admin_management_keyboard(await store.list_admins()),
    )
    try:
        await bot.send_message(
            telegram_id,
            "👑 <b>Admin access granted</b>\n\n"
            "You can now open the admin panel with /admin.",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin:admins:remove:"))
async def remove_admin(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store) or not store.is_owner(query.from_user.id):
        await query.answer("Only owners can remove admins.", show_alert=True)
        return
    telegram_id = int(query.data.rsplit(":", 1)[1])
    removed, error = await store.remove_admin(telegram_id)
    if not removed:
        await query.answer(error or "Could not remove admin.", show_alert=True)
        return
    await query.answer("Admin access removed.", show_alert=True)
    admins = await store.list_admins()
    await query.message.edit_text(
        "👑 <b>Admin Management</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Admin removed successfully.",
        reply_markup=admin_management_keyboard(admins),
    )


async def send_all_users_page(
    target: Message | CallbackQuery,
    store: MongoStore,
    settings: Settings,
    page: int,
) -> None:
    total = await store.count_users()
    items = await store.list_users(page * PAGE_SIZE, PAGE_SIZE)
    text = (
        f"📋 <b>All Users</b> · page {page + 1}\n"
        f"Total accounts: <b>{total}</b>\n\n"
        "Select a user card below to manage balance or role."
    )
    keyboard = pagination_keyboard(
        "all_users", page, page > 0, (page + 1) * PAGE_SIZE < total
    )
    if isinstance(target, CallbackQuery):
        await target.answer()
        await target.message.edit_text(text, reply_markup=keyboard)
        send_message = target.message.answer
    else:
        await target.answer(text, reply_markup=keyboard)
        send_message = target.answer
    for item in items:
        await send_message(
            f"👤 <b>{escape(item['custom_uid'])}</b>\n"
            f"Telegram: <code>{item['telegram_id']}</code>\n"
            f"Role: <b>{escape(str(item['role']))}</b>\n"
            f"Status: <b>{escape(str(item['status']))}</b>\n"
            f"Balance: <b>{money(item['balance'])}</b>",
            reply_markup=user_management_keyboard(item["telegram_id"], item["role"]),
        )


@router.callback_query(F.data.startswith("admin:all_users:"))
async def all_users_page(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    page = int(query.data.rsplit(":", 1)[1])
    await send_all_users_page(query, store, settings, page)


@router.callback_query(F.data.startswith("admin:users:"))
async def pending_users(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    page = int(query.data.rsplit(":", 1)[1])
    total = await store.count_pending_users()
    items = await store.list_pending_users(page * PAGE_SIZE, PAGE_SIZE)
    if not items:
        await query.answer("No pending users")
        await query.message.edit_text(
            "👤 <b>Pending users</b>\n\nNo pending users.",
            reply_markup=pagination_keyboard("users", page, page > 0, False),
        )
        return
    lines = [f"👤 <b>Pending users</b> · page {page + 1}"]
    for item in items:
        lines.append(
            f"\nUID: <code>{escape(item['custom_uid'])}</code>\n"
            f"Telegram: <code>{item['telegram_id']}</code>\n"
            f"Role: {item['role']}"
        )
    await query.answer()
    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=pagination_keyboard(
            "users", page, page > 0, (page + 1) * PAGE_SIZE < total
        ),
    )
    for item in items:
        review_text = (
            f"Review <code>{escape(item['custom_uid'])}</code> "
            f"(<code>{item['telegram_id']}</code>)"
        )
        sent = await query.message.answer(
            review_text,
            reply_markup=approval_keyboard("user", str(item["telegram_id"])),
        )
        await store.record_admin_notification(
            f"user:{item['telegram_id']}",
            query.from_user.id,
            sent.message_id,
            "text",
            review_text,
        )


@router.callback_query(F.data.startswith("admin:teams:"))
async def pending_teams(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    page = int(query.data.rsplit(":", 1)[1])
    total = await store.count_pending_team_additions()
    items = await store.list_pending_team_additions(page * PAGE_SIZE, PAGE_SIZE)
    lines = [f"👥 <b>Pending team additions</b> · page {page + 1}"]
    for item in items:
        lines.append(
            f"\nUID: <code>{escape(item['custom_uid'])}</code>\n"
            f"Member Telegram: <code>{item['member_telegram_id']}</code>\n"
            f"Agent: <code>{item['agent_id']}</code>"
        )
    await query.answer()
    await query.message.edit_text(
        "\n".join(lines) if items else "\n".join(lines + ["\nNo pending team additions."]),
        reply_markup=pagination_keyboard(
            "teams", page, page > 0, (page + 1) * PAGE_SIZE < total
        ),
    )
    for item in items:
        review_text = f"Review team request <code>{escape(item['custom_uid'])}</code>"
        sent = await query.message.answer(
            review_text,
            reply_markup=approval_keyboard("team", item["addition_id"]),
        )
        await store.record_admin_notification(
            f"team:{item['addition_id']}",
            query.from_user.id,
            sent.message_id,
            "text",
            review_text,
        )


@router.callback_query(F.data.startswith("admin:withdrawals:"))
async def pending_withdrawals(
    query: CallbackQuery, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    page = int(query.data.rsplit(":", 1)[1])
    total = await store.count_pending_withdrawals()
    items = await store.list_pending_withdrawals(page * PAGE_SIZE, PAGE_SIZE)
    lines = [f"💸 <b>Pending withdrawals</b> · page {page + 1}"]
    for item in items:
        lines.append(
            f"\nUser: <code>{item['user_id']}</code>\n"
            f"Amount: <b>₹{item['amount']:.2f}</b>\n"
            f"Payment: <code>{escape(item['payment_method'])}</code>"
        )
    await query.answer()
    await query.message.edit_text(
        "\n".join(lines) if items else "\n".join(lines + ["\nNo pending withdrawals."]),
        reply_markup=pagination_keyboard(
            "withdrawals", page, page > 0, (page + 1) * PAGE_SIZE < total
        ),
    )
    for item in items:
        review_text = (
            f"Review withdrawal <b>₹{item['amount']:.2f}</b> from "
            f"<code>{item['user_id']}</code>"
        )
        sent = await query.message.answer(
            review_text,
            reply_markup=approval_keyboard("withdrawal", item["withdrawal_id"]),
        )
        await store.record_admin_notification(
            f"withdrawal:{item['withdrawal_id']}",
            query.from_user.id,
            sent.message_id,
            "text",
            review_text,
        )


@router.callback_query(F.data.startswith("admin:tasks:"))
async def pending_tasks(
    query: CallbackQuery, store: MongoStore, settings: Settings, bot
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    page = int(query.data.rsplit(":", 1)[1])
    total = await store.count_pending_tasks()
    items = await store.list_pending_tasks(page * PAGE_SIZE, PAGE_SIZE)
    lines = [f"🧾 <b>Pending Task Submissions</b> · page {page + 1}"]
    for item in items:
        lines.append(
            f"\nTask: <code>{item['task_id'][:8]}</code>\n"
            f"User: <code>{item['user_id']}</code>\n"
            f"Description: {escape(item['description'])[:180]}\n"
            f"Proof screenshots: <b>{len(item.get('proof_file_ids', []))}</b>"
        )
    await query.answer()
    await query.message.edit_text(
        "\n".join(lines)
        if items
        else "\n".join(lines + ["\nNo pending task submissions."]),
        reply_markup=pagination_keyboard(
            "tasks", page, page > 0, (page + 1) * PAGE_SIZE < total
        ),
    )
    for item in items:
        review_text = (
            f"Review task <code>{item['task_id'][:8]}</code> from "
            f"<code>{item['user_id']}</code>"
        )
        sent = await query.message.answer(
            review_text,
            reply_markup=approval_keyboard("task", item["task_id"]),
        )
        await store.record_admin_notification(
            f"task:{item['task_id']}",
            query.from_user.id,
            sent.message_id,
            "text",
            review_text,
        )
        for index, file_id in enumerate(item.get("proof_file_ids", []), start=1):
            try:
                caption = (
                    f"📸 Task {item['task_id'][:8]} proof "
                    f"{index}/{len(item.get('proof_file_ids', []))}"
                )
                sent = await bot.send_photo(
                    query.from_user.id,
                    file_id,
                    caption=caption,
                    reply_markup=(
                        approval_keyboard("task", item["task_id"])
                        if index == len(item.get("proof_file_ids", []))
                        else None
                    ),
                )
                await store.record_admin_notification(
                    f"task:{item['task_id']}",
                    query.from_user.id,
                    sent.message_id,
                    "photo",
                    sent.caption or caption,
                )
            except Exception:
                continue


@router.callback_query(F.data == "admin:search")
async def start_search(
    query: CallbackQuery, state: FSMContext, settings: Settings, store: MongoStore
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    await state.set_state(AdminSearchStates.query)
    await query.answer()
    await query.message.edit_text(
        "🔎 Send a user's exact Telegram ID or part of their custom UID.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminSearchStates.query)
async def search_users(
    message: Message, state: FSMContext, store: MongoStore, settings: Settings
) -> None:
    if not admin_only(message, settings, store):
        return
    results = await store.search_users(message.text or "")
    await state.clear()
    if not results:
        await message.answer("No matching users found.")
        return
    for user in results:
        await message.answer(
            f"👤 <b>{escape(user['custom_uid'])}</b>\n"
            f"Telegram: <code>{user['telegram_id']}</code>\n"
            f"Role: {escape(user['role'])}\n"
            f"Status: {escape(user['status'])}\n"
            f"Balance: <b>₹{user['balance']:.2f}</b>",
            reply_markup=user_management_keyboard(user["telegram_id"], user["role"]),
        )


@router.callback_query(F.data.startswith("admin:approve:"))
async def approve_item(
    query: CallbackQuery,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
    bot,
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    _, _, kind, item_id = query.data.split(":", 3)
    request_key: str | None = None
    decision: str | None = None
    actor_role = "Owner" if store.is_owner(query.from_user.id) else "Admin"
    if kind == "user":
        item = await store.set_user_status(int(item_id), Status.APPROVED)
        if item:
            try:
                await send_message_with_effect(
                    bot,
                    int(item_id),
                    "🎉 <b>Welcome to iPAY Bot!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "Your registration is approved. Your account is ready—"
                    "send /start to open your dashboard.",
                    effect_id=PARTY_POPPER,
                )
            except Exception:
                pass
            text = "✅ User approved."
            request_key = f"user:{item_id}"
            decision = (
                f"✅ <b>Approved</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
        else:
            text = "This user is no longer pending."
    elif kind == "team":
        item, error = await store.approve_team_addition(item_id)
        if error:
            text = f"Could not approve: {error}"
        else:
            try:
                await send_message_with_effect(
                    bot,
                    item["member_telegram_id"],
                    "🎉 <b>Welcome to iPAY Bot!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "Your team registration is approved. Send /start to open "
                    "your dashboard.",
                    effect_id=PARTY_POPPER,
                )
            except Exception:
                pass
            try:
                await bot.send_message(
                    item["agent_id"],
                    f"✅ Team member <code>{escape(item['custom_uid'])}</code> was approved.",
                )
            except Exception:
                pass
            text = "✅ Team addition approved."
            request_key = f"team:{item_id}"
            decision = (
                f"✅ <b>Approved</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
    elif kind == "withdrawal":
        withdrawal = await store.get_withdrawal(item_id)
        if not withdrawal or withdrawal["status"] != WithdrawalStatus.PENDING:
            text = "This withdrawal is no longer pending."
        else:
            updated_user = await store.adjust_balance(
                withdrawal["user_id"],
                withdrawal["amount"],
                TransactionType.DEBIT,
                "Approved withdrawal",
            )
            if not updated_user:
                text = "Insufficient balance; withdrawal remains pending."
            else:
                await store.set_withdrawal_status(item_id, WithdrawalStatus.APPROVED)
                try:
                    await bot.send_message(
                        withdrawal["user_id"],
                        f"✅ Withdrawal approved: ₹{withdrawal['amount']:.2f}.",
                    )
                except Exception:
                    pass
                text = "✅ Withdrawal approved and balance debited."
                request_key = f"withdrawal:{item_id}"
                decision = (
                    f"✅ <b>Approved</b> by {actor_role} "
                    f"<code>{query.from_user.id}</code>."
                )
    elif kind == "task":
        task = await store.get_task(item_id)
        if not task or task["status"] != "Pending":
            text = "This task is no longer pending."
        else:
            await state.update_data(task_id=item_id)
            await state.set_state(TaskRewardStates.amount)
            await query.message.answer(
                f"💰 <b>Task reward</b>\n\n"
                f"Task <code>{item_id[:8]}</code> is ready for approval.\n"
                "Send the reward amount to credit to the user.",
                reply_markup=cancel_keyboard(),
            )
            text = "Send the reward amount in your next message."
    else:
        text = "Unknown approval type."
    if request_key and decision:
        await sync_admin_notifications(bot, store, request_key, decision)
    await query.answer(text[:200], show_alert=True)
    await query.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("admin:reject:"))
async def reject_item(
    query: CallbackQuery, store: MongoStore, settings: Settings, bot
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    _, _, kind, item_id = query.data.split(":", 3)
    request_key: str | None = None
    decision: str | None = None
    actor_role = "Owner" if store.is_owner(query.from_user.id) else "Admin"
    if kind == "user":
        item = await store.set_user_status(int(item_id), Status.REJECTED)
        if item:
            try:
                await notify_registration_rejected(bot, int(item_id))
            except Exception:
                pass
            text = "User rejected."
            request_key = f"user:{item_id}"
            decision = (
                f"❌ <b>Rejected</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
        else:
            text = "This user is no longer pending."
    elif kind == "team":
        item = await store.set_team_addition_status(item_id, Status.REJECTED)
        if item:
            try:
                await bot.send_message(
                    item["agent_id"], "Your team addition request was rejected."
                )
            except Exception:
                pass
            text = "Team addition rejected."
            request_key = f"team:{item_id}"
            decision = (
                f"❌ <b>Rejected</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
        else:
            text = "This team request is no longer pending."
    elif kind == "withdrawal":
        item = await store.set_withdrawal_status(item_id, WithdrawalStatus.REJECTED)
        if item:
            try:
                await bot.send_message(
                    item["user_id"], "Your withdrawal request was rejected."
                )
            except Exception:
                pass
            text = "Withdrawal rejected."
            request_key = f"withdrawal:{item_id}"
            decision = (
                f"❌ <b>Rejected</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
        else:
            text = "This withdrawal is no longer pending."
    elif kind == "task":
        item = await store.reject_task(
            item_id, query.from_user.id, "Proof was rejected by admin."
        )
        if item:
            try:
                await bot.send_message(
                    item["user_id"],
                    f"❌ <b>Task rejected</b>\n\n"
                    f"Task ID: <code>{item_id[:8]}</code>\n"
                    "The submitted proof did not meet the requirements. "
                    "You can submit the task again with clearer proof.",
                )
            except Exception:
                pass
            text = "Task rejected and user notified."
            request_key = f"task:{item_id}"
            decision = (
                f"❌ <b>Rejected</b> by {actor_role} "
                f"<code>{query.from_user.id}</code>."
            )
        else:
            text = "This task is no longer pending."
    else:
        text = "Unknown rejection type."
    if request_key and decision:
        await sync_admin_notifications(bot, store, request_key, decision)
    await query.answer(text, show_alert=True)
    await query.message.edit_reply_markup(reply_markup=None)


@router.message(TaskRewardStates.amount)
async def apply_task_reward(
    message: Message,
    state: FSMContext,
    store: MongoStore,
    settings: Settings,
    bot,
) -> None:
    if not admin_only(message, settings, store):
        return
    raw_amount = (message.text or "").strip()
    try:
        amount = round(float(raw_amount), 2)
    except ValueError:
        await message.answer("Send a valid numeric reward amount, for example: 250")
        return
    if not isfinite(amount) or amount <= 0:
        await message.answer("Reward amount must be greater than zero.")
        return
    data = await state.get_data()
    task, error = await store.approve_task_with_reward(
        data["task_id"], message.from_user.id, amount
    )
    if error:
        await state.clear()
        await message.answer(f"❌ Could not approve task: {escape(error)}")
        return
    await state.clear()
    user = await store.get_user(task["user_id"])
    await message.answer(
        f"✅ <b>Task approved</b>\n\n"
        f"Reward credited: <b>{money(amount)}</b>\n"
        f"User: <code>{task['user_id']}</code>"
    )
    actor_role = "Owner" if store.is_owner(message.from_user.id) else "Admin"
    await sync_admin_notifications(
        bot,
        store,
        f"task:{task['task_id']}",
        f"✅ <b>Approved</b> by {actor_role} "
        f"<code>{message.from_user.id}</code>. "
        f"Reward: <b>{money(amount)}</b>.",
    )
    if user:
        try:
            await send_message_with_effect(
                bot,
                task["user_id"],
                f"🎉 <b>Task approved!</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"Task ID: <code>{task['task_id'][:8]}</code>\n"
                f"Reward credited: <b>{money(amount)}</b>\n"
                f"New wallet balance: <b>{money(user['balance'])}</b>\n\n"
                "Your reward has been added to your account.",
                effect_id=FIRE,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("admin:fund:"))
async def start_fund_adjustment(
    query: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    store: MongoStore,
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    _, _, action, telegram_id = query.data.split(":", 3)
    await state.update_data(action=action, telegram_id=int(telegram_id))
    await state.set_state(FundAdjustmentStates.amount)
    await query.answer()
    await query.message.answer(
        f"Send the amount to {action} for <code>{telegram_id}</code>.",
        reply_markup=cancel_keyboard(),
    )


@router.message(FundAdjustmentStates.amount)
async def apply_fund_adjustment(
    message: Message, state: FSMContext, store: MongoStore, settings: Settings, bot
) -> None:
    if not admin_only(message, settings, store):
        return
    try:
        amount = round(float((message.text or "").strip()), 2)
    except ValueError:
        await message.answer("Send a valid amount.")
        return
    if amount <= 0:
        await message.answer("Amount must be greater than zero.")
        return
    data = await state.get_data()
    transaction_type = (
        TransactionType.CREDIT if data["action"] == "add" else TransactionType.DEBIT
    )
    user = await store.adjust_balance(
        data["telegram_id"], amount, transaction_type, "Admin balance adjustment"
    )
    if not user:
        await message.answer("Could not adjust the balance. The user may not exist or may lack funds.")
        return
    await state.clear()
    await message.answer(f"✅ New balance: ₹{user['balance']:.2f}")
    await bot.send_message(
        data["telegram_id"],
        f"💰 Admin updated your wallet. New balance: ₹{user['balance']:.2f}",
    )


@router.callback_query(F.data.startswith("admin:role:"))
async def change_role(
    query: CallbackQuery, store: MongoStore, settings: Settings, bot
) -> None:
    if not admin_only(query, settings, store):
        await query.answer("Unauthorized", show_alert=True)
        return
    _, _, role_name, telegram_id = query.data.split(":", 3)
    role = Role.AGENT if role_name == "agent" else Role.USER
    user = await store.set_role(int(telegram_id), role)
    if not user:
        await query.answer("User not found", show_alert=True)
        return
    await query.answer(f"Role set to {role.value}", show_alert=True)
    await query.message.edit_reply_markup(
        reply_markup=user_management_keyboard(user["telegram_id"], user["role"])
    )
    await bot.send_message(
        user["telegram_id"], f"Your account role is now <b>{role.value}</b>."
    )