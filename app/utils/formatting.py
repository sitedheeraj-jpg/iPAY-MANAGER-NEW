from __future__ import annotations

from html import escape
from typing import Any

from app.models import TransactionType


def money(value: float | int) -> str:
    return f"₹{float(value):,.2f}"


def dashboard_text(user: dict[str, Any], display_name: str | None = None) -> str:
    name = escape(display_name or "there")
    role = escape(str(user["role"]))
    uid = escape(str(user["custom_uid"]))
    agent_line = (
        "\n👥 <b>Agent tools:</b> Add and manage your team"
        if str(user["role"]) == "Agent"
        else ""
    )
    return (
        f"👋 <b>Welcome back, {name}!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 UID: <code>{uid}</code>\n"
        f"👤 Role: <b>{role}</b>\n"
        f"💳 Wallet: <b>{money(user['balance'])}</b>\n"
        f"📌 Status: <b>{escape(str(user['status']))}</b>"
        f"{agent_line}\n\n"
        "Choose an option below or use the menu commands."
    )


def profile_text(user: dict[str, Any], display_name: str | None = None) -> str:
    return (
        f"👤 <b>My Profile</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Name: <b>{escape(display_name or 'Not available')}</b>\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"Custom UID: <code>{escape(str(user['custom_uid']))}</code>\n"
        f"Role: <b>{escape(str(user['role']))}</b>\n"
        f"Account status: <b>{escape(str(user['status']))}</b>\n"
        f"Wallet balance: <b>{money(user['balance'])}</b>"
    )


def transaction_history_text(transactions: list[dict[str, Any]]) -> str:
    if not transactions:
        return "📜 <b>Balance History</b>\n━━━━━━━━━━━━━━━━━━\nNo transactions yet."
    lines = ["📜 <b>Balance History</b>", "━━━━━━━━━━━━━━━━━━"]
    for item in transactions:
        sign = "+" if item["type"] == TransactionType.CREDIT else "-"
        timestamp = item["timestamp"].strftime("%d %b %Y · %H:%M UTC")
        balance_after = item.get("balance_after")
        after = f" · Balance {money(balance_after)}" if balance_after is not None else ""
        lines.append(
            f"{sign}<b>{money(item['amount'])}</b> · {escape(str(item['reason']))}\n"
            f"<i>{timestamp}{after}</i>"
        )
    return "\n\n".join(lines)


def team_text(members: list[dict[str, Any]]) -> str:
    if not members:
        return (
            "👥 <b>My Team</b>\n━━━━━━━━━━━━━━━━━━\n"
            "No approved team members yet.\nUse Add Team to submit a member."
        )
    lines = [f"👥 <b>My Team</b> · {len(members)} member(s)", "━━━━━━━━━━━━━━━━━━"]
    for member in members:
        lines.append(
            f"• <b>{escape(str(member['custom_uid']))}</b> · "
            f"<code>{member['telegram_id']}</code>\n"
            f"  Status: {escape(str(member['status']))} · "
            f"Balance: {money(member['balance'])}"
        )
    return "\n\n".join(lines)


def task_history_text(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "📋 <b>My Task Submissions</b>\n━━━━━━━━━━━━━━━━━━\nNo tasks submitted yet."
    lines = ["📋 <b>My Task Submissions</b>", "━━━━━━━━━━━━━━━━━━"]
    for task in tasks:
        created = task["created_at"].strftime("%d %b %Y · %H:%M UTC")
        reward = (
            f" · Reward {money(task['reward_amount'])}"
            if task.get("reward_amount")
            else ""
        )
        description = escape(str(task["description"]))[:120]
        lines.append(
            f"🧾 <code>{task['task_id'][:8]}</code> · "
            f"<b>{escape(str(task['status']))}</b>{reward}\n"
            f"{description}\n<i>{created}</i>"
        )
    return "\n\n".join(lines)


HELP_TEXT = (
    "ℹ️ <b>Help & Commands</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "/start — Register or open your dashboard\n"
    "/menu — Open the main dashboard\n"
    "/profile — View your profile and UID\n"
    "/balance — View your wallet balance\n"
    "/history — View the last 10 transactions\n"
    "/withdraw — Request a UPI withdrawal\n"
    "/submit_task — Submit task details and screenshot proof\n"
    "/my_tasks — View your submitted task statuses\n"
    "/add_team — Add a team member (agents only)\n"
    "/team — View your approved team (agents only)\n"
    "/id — Show your Telegram ID\n"
    "/cancel — Cancel the current form\n"
    "/help — Show this help\n\n"
    "Your account stays locked until an administrator approves it."
)