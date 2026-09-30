from app.config.settings import Settings
from app.handlers.deps import sync_admin_notifications
from app.handlers.start import (
    REGISTRATION_PROMPT_TEXT,
    command_start,
    notify_registration_rejected,
    receive_custom_uid,
)
from app.keyboards.registration import (
    IPAY_REGISTRATION_URL,
    registration_prompt_keyboard,
    registration_rejected_keyboard,
)
from app.handlers.user import approved_user
from app.utils.effects import FIRE, HEART, PARTY_POPPER, STARSTRUCK, THUMBS_DOWN
from app.utils.telegram_messaging import send_message_with_effect

import asyncio
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage


def test_admin_ids_parse_from_csv() -> None:
    settings = Settings(
        bot_token="token",
        mongodb_uri="mongodb://localhost",
        admin_ids="100, 200",
    )
    assert settings.admin_ids == [100, 200]


def test_admin_ids_parse_from_single_number() -> None:
    settings = Settings(
        bot_token="token",
        mongodb_uri="mongodb://localhost",
        admin_ids=123456789,
    )
    assert settings.admin_ids == [123456789]


def test_legacy_admin_ids_become_owners() -> None:
    settings = Settings(
        bot_token="token",
        mongodb_uri="mongodb://localhost",
        admin_ids="100,200",
    )
    assert settings.owner_ids == [100, 200]


def test_owner_ids_parse_from_csv() -> None:
    settings = Settings(
        bot_token="token",
        mongodb_uri="mongodb://localhost",
        owner_ids="300, 400",
    )
    assert settings.owner_ids == [300, 400]


def test_environment_csv_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost")
    monkeypatch.setenv("OWNER_IDS", "500, 600")
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    settings = Settings()
    assert settings.owner_ids == [500, 600]


def test_environment_json_array_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost")
    monkeypatch.setenv("OWNER_IDS", "[700, 800]")
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    settings = Settings()
    assert settings.owner_ids == [700, 800]


def test_callback_approval_uses_clicking_user_not_bot_message_author() -> None:
    class User:
        id = 9001

    class DashboardMessage:
        # Telegram sets this to the bot's ID for a bot-sent dashboard message.
        from_user = type("BotUser", (), {"id": 9999})()

        async def answer(self, *_args, **_kwargs):
            raise AssertionError("An approved user should not see the locked message")

    class Store:
        async def get_user(self, telegram_id: int):
            if telegram_id == User.id:
                return {"telegram_id": telegram_id, "status": "Approved"}
            return None

    user = asyncio.run(approved_user(DashboardMessage(), Store(), User.id))
    assert user["telegram_id"] == User.id


def test_admin_decision_sync_updates_all_notification_copies() -> None:
    class Bot:
        def __init__(self):
            self.edits = []

        async def edit_message_text(self, **kwargs):
            self.edits.append(("text", kwargs))

        async def edit_message_caption(self, **kwargs):
            self.edits.append(("photo", kwargs))

        async def edit_message_reply_markup(self, **kwargs):
            self.edits.append(("markup", kwargs))

    class Store:
        def __init__(self):
            self.resolved = []

        async def list_active_admin_notifications(self, request_key):
            assert request_key == "user:123"
            return [
                {
                    "chat_id": 10,
                    "message_id": 20,
                    "content_type": "text",
                    "content": "🆕 New user",
                },
                {
                    "chat_id": 11,
                    "message_id": 21,
                    "content_type": "photo",
                    "content": "📸 Proof",
                },
            ]

        async def resolve_admin_notification(self, chat_id, message_id, decision):
            self.resolved.append((chat_id, message_id, decision))

    bot = Bot()
    store = Store()
    asyncio.run(
        sync_admin_notifications(
            bot, store, "user:123", "✅ Approved by Owner <code>1</code>."
        )
    )
    assert len(bot.edits) == 2
    assert len(store.resolved) == 2
    assert "Approved" in bot.edits[0][1]["text"]
    assert "Approved" in bot.edits[1][1]["caption"]


def test_ipay_registration_screen_and_green_buttons() -> None:
    assert "Welcome to iPAY Bot" in REGISTRATION_PROMPT_TEXT
    assert "<blockquote expandable>" in REGISTRATION_PROMPT_TEXT
    assert "Every UID can be used only once" in REGISTRATION_PROMPT_TEXT

    prompt_buttons = [
        button
        for row in registration_prompt_keyboard().inline_keyboard
        for button in row
    ]
    register = next(button for button in prompt_buttons if button.url)
    cancel = next(button for button in prompt_buttons if button.callback_data)
    assert register.url == IPAY_REGISTRATION_URL
    assert register.style == "success"
    assert cancel.callback_data == "common:cancel"

    rejected_buttons = [
        button
        for row in registration_rejected_keyboard().inline_keyboard
        for button in row
    ]
    register = next(button for button in rejected_buttons if button.url)
    retry = next(button for button in rejected_buttons if button.callback_data)
    assert register.url == IPAY_REGISTRATION_URL
    assert register.style == "success"
    assert retry.callback_data == "registration:retry"


def test_requested_telegram_effect_ids_are_configured() -> None:
    assert HEART == "5159385139981059251"
    assert THUMBS_DOWN == "5104858069142078462"
    assert PARTY_POPPER == "5046509860389126442"
    assert STARSTRUCK == "5170169077011841524"
    assert FIRE == "5104841245755180586"


def test_invalid_message_effect_retries_without_effect() -> None:
    class Bot:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            if len(self.calls) == 1:
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=chat_id, text=text),
                    message="Bad Request: EFFECT_ID_INVALID",
                )
            return "sent without animation"

    bot = Bot()
    result = asyncio.run(
        send_message_with_effect(
            bot, 601, "Welcome", effect_id=HEART, reply_markup="same keyboard"
        )
    )
    assert result == "sent without animation"
    assert len(bot.calls) == 2
    assert bot.calls[0][2]["message_effect_id"] == HEART
    assert "message_effect_id" not in bot.calls[1][2]
    assert bot.calls[1][2]["reply_markup"] == "same keyboard"


def test_start_prompt_survives_telegram_effect_id_error() -> None:
    from types import SimpleNamespace

    class State:
        async def set_state(self, _state):
            pass

        async def update_data(self, **_kwargs):
            pass

    class Store:
        async def get_user(self, _telegram_id):
            return None

    class Bot:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=chat_id, text=text),
                    message="Bad Request: EFFECT_ID_INVALID",
                )
            return SimpleNamespace(
                chat=SimpleNamespace(id=chat_id), message_id=902
            )

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=601),
        chat=SimpleNamespace(id=501),
    )
    bot = Bot()
    asyncio.run(command_start(message, State(), Store(), bot))
    assert len(bot.calls) == 2
    assert bot.calls[0]["message_effect_id"] == HEART
    assert "message_effect_id" not in bot.calls[1]
    assert bot.calls[1]["reply_markup"] is not None


def test_unrelated_telegram_error_is_not_hidden_by_effect_fallback() -> None:
    class Bot:
        async def send_message(self, chat_id, text, **kwargs):
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=text),
                message="Bad Request: CHAT_NOT_FOUND",
            )

    with pytest.raises(TelegramBadRequest, match="CHAT_NOT_FOUND"):
        asyncio.run(
            send_message_with_effect(Bot(), 601, "Welcome", effect_id=HEART)
        )


def test_valid_uid_is_deleted_and_welcome_message_is_edited() -> None:
    class State:
        def __init__(self):
            self.data = {
                "registration_prompt_chat_id": 501,
                "registration_prompt_message_id": 502,
            }

        async def get_data(self):
            return dict(self.data)

        async def clear(self):
            self.data.clear()

    class Bot:
        def __init__(self):
            self.deleted = []
            self.edits = []

        async def delete_message(self, chat_id, message_id):
            self.deleted.append((chat_id, message_id))

        async def edit_message_text(self, **kwargs):
            self.edits.append(kwargs)

        async def send_message(self, *args, **kwargs):
            raise AssertionError("The saved welcome message should be edited")

    class Store:
        async def register_user(self, telegram_id, custom_uid):
            assert telegram_id == 601
            assert custom_uid == "IPAY_123"
            return {"telegram_id": telegram_id, "status": "Pending"}

        async def list_admin_ids(self):
            return []

    message = type(
        "IncomingMessage",
        (),
        {
            "text": "IPAY_123",
            "chat": type("Chat", (), {"id": 501})(),
            "message_id": 700,
            "from_user": type(
                "User", (), {"id": 601, "full_name": "Test Member"}
            )(),
        },
    )()
    bot = Bot()
    asyncio.run(
        receive_custom_uid(
            message,
            State(),
            Store(),
            bot,
            Settings(bot_token="token", mongodb_uri="mongodb://localhost"),
        )
    )
    assert bot.deleted == [(501, 700)]
    assert bot.edits[0]["chat_id"] == 501
    assert bot.edits[0]["message_id"] == 502
    assert "Registration submitted" in bot.edits[0]["text"]


def test_rejection_message_uses_requested_effect_and_retry_button() -> None:
    class Bot:
        async def send_message(self, telegram_id, text, **kwargs):
            assert telegram_id == 601
            assert "Registration Rejected" in text
            assert kwargs["message_effect_id"] == THUMBS_DOWN
            buttons = [
                button
                for row in kwargs["reply_markup"].inline_keyboard
                for button in row
            ]
            assert any(button.url == IPAY_REGISTRATION_URL for button in buttons)
            assert any(button.callback_data == "registration:retry" for button in buttons)

    asyncio.run(notify_registration_rejected(Bot(), 601))