from aiogram.filters.callback_data import CallbackData


class QueuePage(CallbackData, prefix="qp"):
    page: int


class OpportunityAction(CallbackData, prefix="oa"):
    opp_id: int
    action: str  # approve | reject | edit | schedule | hooks | view


class FieldSelect(CallbackData, prefix="fs"):
    opp_id: int
    field: str


class HookToggle(CallbackData, prefix="ht"):
    opp_id: int
    hook_key: str


class AudienceChoice(CallbackData, prefix="ac"):
    opp_id: int
    value: str  # school | university | both


class SearchPage(CallbackData, prefix="sp"):
    query: str
    page: int
