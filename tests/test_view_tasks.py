from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot


def _admin_update(**kwargs):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private", id=bot.ADMIN_ID),
        **kwargs,
    )


def test_build_view_category_keyboard_matches_categories_plus_all() -> None:
    keyboard = bot._build_view_category_keyboard()

    assert len(keyboard.inline_keyboard) == len(bot.CATEGORIES) + 1
    for row, category in zip(keyboard.inline_keyboard, bot.CATEGORIES):
        assert row[0].text == category
    assert keyboard.inline_keyboard[-1][0].text == "ВСЕ"
    assert keyboard.inline_keyboard[-1][0].callback_data == "viewcat:all"


def test_build_view_category_keyboard_scales_to_any_number_of_categories(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bot, "CATEGORIES", ["#A", "#B", "#C", "#D", "#E", "#F", "#G"])

    keyboard = bot._build_view_category_keyboard()

    assert len(keyboard.inline_keyboard) == 8  # 7 categories + ВСЕ
    assert keyboard.inline_keyboard[-1][0].callback_data == "viewcat:all"


@pytest.mark.asyncio
async def test_view_start_sends_category_keyboard() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))

    await bot.view_start(update, SimpleNamespace())

    args, kwargs = update.message.reply_text.call_args
    assert args[0] == "Какую категорию показать?"
    assert len(kwargs["reply_markup"].inline_keyboard) == len(bot.CATEGORIES) + 1


@pytest.mark.asyncio
async def test_view_category_chosen_shows_pool_picker() -> None:
    query = SimpleNamespace(
        data="viewcat:0", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)

    await bot.view_category_chosen(update, SimpleNamespace())

    query.answer.assert_called_once()
    args, kwargs = query.edit_message_text.call_args
    assert bot.CATEGORIES[0] in args[0]
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == [
        "viewpool:0:tasks",
        "viewpool:0:available",
        "viewpool:0:used",
        "viewback",
    ]


@pytest.mark.asyncio
async def test_view_category_chosen_all() -> None:
    query = SimpleNamespace(
        data="viewcat:all", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)

    await bot.view_category_chosen(update, SimpleNamespace())

    args, kwargs = query.edit_message_text.call_args
    assert "ВСЕ" in args[0]
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == [
        "viewpool:all:tasks",
        "viewpool:all:available",
        "viewpool:all:used",
        "viewback",
    ]


@pytest.mark.asyncio
async def test_view_back_chosen_returns_to_category_picker() -> None:
    query = SimpleNamespace(
        data="viewback", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)

    await bot.view_back_chosen(update, SimpleNamespace())

    args, kwargs = query.edit_message_text.call_args
    assert args[0] == "Какую категорию показать?"
    assert len(kwargs["reply_markup"].inline_keyboard) == len(bot.CATEGORIES) + 1


@pytest.mark.asyncio
async def test_view_pool_chosen_single_category(minimal_state) -> None:
    minimal_state["tasks"]["#АРТИСТ"] = ["first added", "second added"]
    await bot.save_state(minimal_state)

    query = SimpleNamespace(
        data="viewpool:0:tasks", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await bot.view_pool_chosen(update, context)

    query.edit_message_text.assert_called_once_with("Список ниже 👇", reply_markup=None)
    args, kwargs = context.bot.send_message.call_args
    text = kwargs["text"]
    assert "#АРТИСТ" in text
    assert "1. first added" in text
    assert "2. second added" in text
    # order is insertion order (added-first), not sorted/shuffled
    assert text.index("first added") < text.index("second added")
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "view_again"


@pytest.mark.asyncio
async def test_view_pool_chosen_all_categories(minimal_state) -> None:
    await bot.save_state(minimal_state)

    query = SimpleNamespace(
        data="viewpool:all:available",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await bot.view_pool_chosen(update, context)

    _, kwargs = context.bot.send_message.call_args
    text = kwargs["text"]
    for category in bot.CATEGORIES:
        assert category in text


@pytest.mark.asyncio
async def test_view_pool_chosen_empty_list_says_so(minimal_state) -> None:
    minimal_state["used"]["#АРТИСТ"] = []
    await bot.save_state(minimal_state)

    query = SimpleNamespace(
        data="viewpool:0:used", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await bot.view_pool_chosen(update, context)

    _, kwargs = context.bot.send_message.call_args
    assert "Список пуст." in kwargs["text"]


@pytest.mark.asyncio
async def test_view_again_chosen_sends_fresh_category_picker() -> None:
    query = SimpleNamespace(data="view_again", answer=AsyncMock())
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await bot.view_again_chosen(update, context)

    query.answer.assert_called_once()
    _, kwargs = context.bot.send_message.call_args
    assert kwargs["text"] == "Какую категорию показать?"
    assert len(kwargs["reply_markup"].inline_keyboard) == len(bot.CATEGORIES) + 1


@pytest.mark.asyncio
async def test_send_long_text_single_message_when_short() -> None:
    send_message = AsyncMock()
    bot_api = SimpleNamespace(send_message=send_message)

    await bot._send_long_text(bot_api, 123, "short text", reply_markup="kb")

    send_message.assert_called_once_with(
        chat_id=123, text="short text", reply_markup="kb"
    )


@pytest.mark.asyncio
async def test_send_long_text_chunks_when_too_long() -> None:
    send_message = AsyncMock()
    bot_api = SimpleNamespace(send_message=send_message)

    long_text = "\n".join(f"{i}. Задание номер {i}" for i in range(1, 400))
    assert len(long_text) > bot._SAFE_CHUNK_SIZE  # sanity check -- а смысл теста?

    await bot._send_long_text(bot_api, 123, long_text, reply_markup="kb")

    assert send_message.call_count > 1
    calls = send_message.call_args_list

    # Только последняя часть содержит markup ответа.
    for call in calls[:-1]:
        assert call.kwargs["reply_markup"] is None
    assert calls[-1].kwargs["reply_markup"] == "kb"

    # Все части по длине находятся под пределом телеги
    for call in calls:
        assert len(call.kwargs["text"]) <= bot.TELEGRAM_MESSAGE_LIMIT
    # перестановка не меняет исход. Крч закон коммутации в этом боте
    reassembled = "\n".join(call.kwargs["text"] for call in calls)
    assert reassembled == long_text
