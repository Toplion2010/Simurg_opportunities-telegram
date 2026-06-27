from aiogram.fsm.state import State, StatesGroup


class EditForm(StatesGroup):
    choose_field = State()
    waiting_value = State()


class ScheduleForm(StatesGroup):
    waiting_datetime = State()


class SearchForm(StatesGroup):
    waiting_query = State()
