from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot


@pytest.mark.asyncio
async def test_publish_command_calls_publish_task(
    monkeypatch, mock_application
) -> None:
    called = False

    async def mock_publish(*args, **kwargs):
        nonlocal called
        called = True
        return {"category": "#АРТИСТ", "task": "A1"}

    monkeypatch.setattr(bot, "publish_task", mock_publish)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    context = SimpleNamespace(application=mock_application)

    await bot.publish_challenge_cmd(update, context)

    assert called is True
    update.message.reply_text.assert_called_once_with("Задание опубликовано для теста.")


def test_build_category_keyboard_matches_categories() -> None:
    keyboard = bot._build_category_keyboard()

    assert len(keyboard.inline_keyboard) == len(bot.CATEGORIES)
    for row, category in zip(keyboard.inline_keyboard, bot.CATEGORIES):
        assert len(row) == 1
        assert row[0].text == category


def test_build_category_keyboard_scales_to_any_number_of_categories(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bot, "CATEGORIES", ["#ONE", "#TWO", "#THREE", "#FOUR", "#FIVE"])

    keyboard = bot._build_category_keyboard()

    assert len(keyboard.inline_keyboard) == 5
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "#ONE",
        "#TWO",
        "#THREE",
        "#FOUR",
        "#FIVE",
    ]
    assert [row[0].callback_data for row in keyboard.inline_keyboard] == [
        "addtask_cat:0",
        "addtask_cat:1",
        "addtask_cat:2",
        "addtask_cat:3",
        "addtask_cat:4",
    ]


@pytest.mark.asyncio
async def test_addtask_start_sends_category_keyboard() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    context = SimpleNamespace(user_data={})

    state = await bot.addtask_start(update, context)

    assert state == bot.ADDTASK_CHOOSING_CATEGORY
    update.message.reply_text.assert_called_once()
    _, kwargs = update.message.reply_text.call_args
    assert len(kwargs["reply_markup"].inline_keyboard) == len(bot.CATEGORIES)


@pytest.mark.asyncio
async def test_addtask_start_blocks_non_admin() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID + 1),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    context = SimpleNamespace(user_data={})

    result = await bot.addtask_start(update, context)

    assert result is None
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_addtask_category_chosen_stores_category_and_prompts_for_text() -> None:
    query = SimpleNamespace(
        data="addtask_cat:1", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=query,
    )
    context = SimpleNamespace(user_data={})

    state = await bot.addtask_category_chosen(update, context)

    assert state == bot.ADDTASK_TYPING_TASK
    assert context.user_data["addtask_category"] == bot.CATEGORIES[1]
    query.answer.assert_called_once()
    _, kwargs = query.edit_message_text.call_args
    assert kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_addtask_category_chosen_handles_stale_index() -> None:
    query = SimpleNamespace(
        data=f"addtask_cat:{len(bot.CATEGORIES) + 5}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        callback_query=query,
    )
    context = SimpleNamespace(user_data={})

    state = await bot.addtask_category_chosen(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data


@pytest.mark.asyncio
async def test_addtask_task_received_saves_task(minimal_state) -> None:
    await bot.save_state(minimal_state)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(text="Новое тестовое задание", reply_text=AsyncMock()),
    )
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_task_received(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    update.message.reply_text.assert_called_once_with(
        "Задание добавлено: #АРТИСТ - Новое тестовое задание"
    )

    saved_state = await bot.load_state()
    assert "Новое тестовое задание" in saved_state["tasks"]["#АРТИСТ"]
    assert "Новое тестовое задание" in saved_state["available"]["#АРТИСТ"]


@pytest.mark.asyncio
async def test_addtask_task_received_rejects_empty_text() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(text="   ", reply_text=AsyncMock()),
    )
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_task_received(update, context)

    assert state == bot.ADDTASK_TYPING_TASK
    assert context.user_data["addtask_category"] == "#АРТИСТ"


@pytest.mark.asyncio
async def test_addtask_cancel_clears_pending_category() -> None:
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID),
        effective_chat=SimpleNamespace(type="private"),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_cancel(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    update.message.reply_text.assert_called_once_with("Добавление задания отменено.")
