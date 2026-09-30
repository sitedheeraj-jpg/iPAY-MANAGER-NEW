from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

IPAY_REGISTRATION_URL = (
    "https://share.ipaynow.net/?data="
    "dWlkPTc4NDU5MyZjaGFubmVsPTEwMDYmYnVzaW5lc3NfaWQ9OTAwMDk2"
)


def registration_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🟢 Register Now",
        url=IPAY_REGISTRATION_URL,
        style="success",
    )
    builder.button(text="✖ Cancel", callback_data="common:cancel", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def registration_rejected_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🟢 iPAY Registration",
        url=IPAY_REGISTRATION_URL,
        style="success",
    )
    builder.button(
        text="↩️ Submit iPAY User ID again",
        callback_data="registration:retry",
        style="primary",
    )
    builder.adjust(1)
    return builder.as_markup()