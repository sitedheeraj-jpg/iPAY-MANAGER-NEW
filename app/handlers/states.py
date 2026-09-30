from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    custom_uid = State()


class WithdrawalStates(StatesGroup):
    amount = State()
    payment_method = State()


class TeamAdditionStates(StatesGroup):
    custom_uid = State()
    telegram_id = State()


class AdminSearchStates(StatesGroup):
    query = State()


class FundAdjustmentStates(StatesGroup):
    amount = State()


class TaskSubmissionStates(StatesGroup):
    description = State()
    proof = State()


class TaskRewardStates(StatesGroup):
    amount = State()


class AdminManagementStates(StatesGroup):
    telegram_id = State()


class BroadcastStates(StatesGroup):
    content = State()
    confirm = State()
