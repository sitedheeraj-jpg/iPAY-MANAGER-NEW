from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def dashboard_keyboard(is_agent: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Profile", callback_data="user:profile", style="primary")
    builder.button(text="💰 Balance", callback_data="user:balance", style="primary")
    builder.button(text="📜 History", callback_data="user:history", style="primary")
    builder.button(text="💸 Withdraw", callback_data="user:withdraw", style="success")
    builder.button(text="🧾 Submit Task", callback_data="user:submit_task", style="success")
    if is_agent:
        builder.button(text="👥 Add Team", callback_data="user:add_team", style="primary")
        builder.button(text="📊 My Team", callback_data="user:team", style="primary")
    builder.button(text="📋 My Tasks", callback_data="user:my_tasks", style="primary")
    builder.button(text="ℹ️ Help", callback_data="user:help", style="primary")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅ Menu", callback_data="user:menu", style="primary")
    return builder.as_markup()


def finish_proof_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Submit Proof to Admin",
        callback_data="task:finish_proof",
        style="success",
    )
    builder.button(text="✖ Cancel", callback_data="common:cancel", style="danger")
    builder.adjust(1)
    return builder.as_markup()