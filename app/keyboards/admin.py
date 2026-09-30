from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_menu_keyboard(
    users: int = 0,
    teams: int = 0,
    withdrawals: int = 0,
    tasks: int = 0,
    can_manage_admins: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 All Users", callback_data="admin:all_users:0")
    builder.button(text=f"👤 Pending Users ({users})", callback_data="admin:users:0")
    builder.button(text=f"👥 Team Requests ({teams})", callback_data="admin:teams:0")
    builder.button(
        text=f"💸 Withdrawals ({withdrawals})", callback_data="admin:withdrawals:0"
    )
    builder.button(text=f"🧾 Task Submissions ({tasks})", callback_data="admin:tasks:0")
    builder.button(text="🔎 Search User", callback_data="admin:search")
    builder.button(text="📢 Broadcast", callback_data="admin:broadcast")
    if can_manage_admins:
        builder.button(text="👑 Manage Admins", callback_data="admin:admins")
    builder.adjust(1)
    return builder.as_markup()


def admin_management_keyboard(admins: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Add Admin", callback_data="admin:admins:add")
    for admin in admins:
        if str(admin.get("role")) == "Owner":
            continue
        telegram_id = int(admin["telegram_id"])
        builder.button(
            text=f"❌ Remove {telegram_id}",
            callback_data=f"admin:admins:remove:{telegram_id}",
            style="danger",
        )
    builder.button(text="⬅ Admin Menu", callback_data="admin:menu")
    builder.adjust(1)
    return builder.as_markup()


def approval_keyboard(kind: str, item_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Approve",
        callback_data=f"admin:approve:{kind}:{item_id}",
        style="success",
    )
    builder.button(
        text="❌ Reject",
        callback_data=f"admin:reject:{kind}:{item_id}",
        style="danger",
    )
    builder.adjust(2)
    return builder.as_markup()


def pagination_keyboard(
    kind: str, page: int, has_previous: bool, has_next: bool
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_previous:
        builder.button(text="◀ Previous", callback_data=f"admin:{kind}:{page - 1}")
    if has_next:
        builder.button(text="Next ▶", callback_data=f"admin:{kind}:{page + 1}")
    builder.button(text="⬅ Admin Menu", callback_data="admin:menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def task_review_keyboard(task_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Approve & Reward",
        callback_data=f"admin:task:approve:{task_id}",
        style="success",
    )
    builder.button(
        text="❌ Reject",
        callback_data=f"admin:task:reject:{task_id}",
        style="danger",
    )
    builder.adjust(2)
    return builder.as_markup()


def user_management_keyboard(
    telegram_id: int, current_role: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Add Balance",
        callback_data=f"admin:fund:add:{telegram_id}",
        style="success",
    )
    builder.button(
        text="➖ Deduct Balance",
        callback_data=f"admin:fund:deduct:{telegram_id}",
        style="danger",
    )
    if current_role == "Agent":
        builder.button(
            text="Set User",
            callback_data=f"admin:role:user:{telegram_id}",
            style="danger",
        )
    else:
        builder.button(
            text="Set Agent",
            callback_data=f"admin:role:agent:{telegram_id}",
            style="success",
        )
    builder.button(text="⬅ Admin Menu", callback_data="admin:menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def broadcast_audience_keyboard(counts: dict[str, int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✅ Approved users ({counts.get('approved', 0)})",
        callback_data="bc:aud:approved",
        style="success",
    )
    builder.button(
        text=f"🧑\u200d💼 Agents only ({counts.get('agents', 0)})",
        callback_data="bc:aud:agents",
        style="primary",
    )
    builder.button(
        text=f"👤 Regular users only ({counts.get('users', 0)})",
        callback_data="bc:aud:users",
        style="primary",
    )
    builder.button(
        text=f"📋 Everyone who started the bot ({counts.get('all', 0)})",
        callback_data="bc:aud:all",
        style="primary",
    )
    builder.button(text="⬅ Admin Menu", callback_data="admin:menu")
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_keyboard(recipients: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🚀 Send to {recipients}",
        callback_data="bc:send",
        style="success",
    )
    builder.button(text="✖ Cancel", callback_data="common:cancel", style="danger")
    builder.adjust(2)
    return builder.as_markup()


def broadcast_progress_keyboard(broadcast_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⛔ Stop broadcast",
        callback_data=f"bc:stop:{broadcast_id}",
        style="danger",
    )
    return builder.as_markup()
