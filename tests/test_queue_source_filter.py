from src.bot.callbacks.data import QueuePage
from src.bot.keyboards.main_menu import main_menu_keyboard
from src.bot.keyboards.queue import pagination_keyboard


def test_main_menu_has_separate_telegram_and_online_queue_buttons():
    kb = main_menu_keyboard()
    labels = {button.text for row in kb.keyboard for button in row}
    assert "📱 Telegram Queue" in labels
    assert "🌐 Online Queue" in labels
    assert "📋 View Queue" not in labels


def test_pagination_keyboard_round_trips_the_source_filter():
    kb = pagination_keyboard(page=1, total_pages=3, source="web")
    packed = [button.callback_data for row in kb.inline_keyboard for button in row]
    for data in packed:
        parsed = QueuePage.unpack(data)
        assert parsed.source == "web"


def test_pagination_keyboard_defaults_to_all_when_source_omitted():
    kb = pagination_keyboard(page=0, total_pages=1)
    data = kb.inline_keyboard[0][0].callback_data
    assert QueuePage.unpack(data).source == "all"
