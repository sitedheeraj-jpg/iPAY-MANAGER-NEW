from aiogram import Bot
from aiogram.types import Message

from app.config import Settings
from app.database import MongoStore
from app.models import Status


def is_admin(user_id: int, settings: Settings, store: MongoStore | None = None) -> bool:
    if store is not None:
        return store.is_admin(user_id)
    return user_id in settings.owner_ids


def is_approved(user: dict | None) -> bool:
    if not user:
        return False
    return str(user.get("status", "")).casefold() == Status.APPROVED.value.casefold()


async def notify_admins(
    bot: Bot,
    settings: Settings,
    text: str,
    reply_markup=None,
    store: MongoStore | None = None,
    notification_key: str | None = None,
) -> None:
    admin_ids = (
        await store.list_admin_ids() if store is not None else settings.owner_ids
    )
    for admin_id in admin_ids:
        try:
            sent = await bot.send_message(admin_id, text, reply_markup=reply_markup)
            if store is not None and notification_key is not None:
                await store.record_admin_notification(
                    notification_key,
                    admin_id,
                    sent.message_id,
                    "text",
                    text,
                )
        except Exception:
            # One blocked admin must not prevent notification of the others.
            continue


async def sync_admin_notifications(
    bot: Bot, store: MongoStore, request_key: str, decision: str
) -> None:
    """Edit every admin/owner copy after one moderator decides a request."""
    notifications = await store.list_active_admin_notifications(request_key)
    for notification in notifications:
        chat_id = int(notification["chat_id"])
        message_id = int(notification["message_id"])
        content = str(notification.get("content", ""))
        updated_content = f"{content}\n\n{decision}"
        try:
            if notification.get("content_type") == "photo":
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=updated_content[:1024],
                    reply_markup=None,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=updated_content[:4096],
                    reply_markup=None,
                )
        except Exception:
            # A moderator may have deleted a message or Telegram may reject
            # an already-edited copy; other admin copies must still update.
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=None
                )
            except Exception:
                pass
        finally:
            await store.resolve_admin_notification(chat_id, message_id, decision)


async def require_approved_user(
    message: Message, store: MongoStore
) -> dict | None:
    user = await store.get_user(message.from_user.id)
    if not is_approved(user):
        await message.answer(
            "Your account is not approved yet. Please wait for an administrator."
        )
        return None
    return user