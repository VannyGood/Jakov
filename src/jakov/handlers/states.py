from aiogram.fsm.state import State, StatesGroup


class ChannelStates(StatesGroup):
    waiting_ref = State()
    waiting_name = State()


class SettingsStates(StatesGroup):
    waiting_zone = State()
    waiting_location = State()
