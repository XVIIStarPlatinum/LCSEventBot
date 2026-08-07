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


def _non_admin_update(**kwargs):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=bot.ADMIN_ID + 1),
        effective_chat=SimpleNamespace(type="private", id=bot.ADMIN_ID + 1),
        **kwargs,
    )


# --- /start (the one unavoidable slash command) ---


@pytest.mark.asyncio
async def test_start_cmd_shows_main_menu() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))

    await bot.start_cmd(update, SimpleNamespace())

    _, kwargs = update.message.reply_text.call_args
    keyboard = kwargs["reply_markup"].keyboard
    assert [row[0].text for row in keyboard] == [
        bot.MENU_ADDTASK_LABEL,
        bot.MENU_PUBLISH_LABEL,
        bot.MENU_VIEW_LABEL,
    ]


# --- addtask: category keyboard building ---


def test_build_category_keyboard_matches_categories_plus_cancel() -> None:
    keyboard = bot._build_category_keyboard()

    assert len(keyboard.inline_keyboard) == len(bot.CATEGORIES) + 1
    for row, category in zip(keyboard.inline_keyboard, bot.CATEGORIES):
        assert len(row) == 1
        assert row[0].text == category
    assert keyboard.inline_keyboard[-1][0].text == bot.MENU_CANCEL_LABEL
    assert keyboard.inline_keyboard[-1][0].callback_data == "addtask_cat:cancel"


def test_build_category_keyboard_scales_to_any_number_of_categories(
    monkeypatch,
) -> None:
    monkeypatch.setattr(bot, "CATEGORIES", ["#ONE", "#TWO", "#THREE", "#FOUR", "#FIVE"])

    keyboard = bot._build_category_keyboard()

    assert len(keyboard.inline_keyboard) == 6  # 5 categories + cancel row
    assert [row[0].text for row in keyboard.inline_keyboard[:5]] == [
        "#ONE",
        "#TWO",
        "#THREE",
        "#FOUR",
        "#FIVE",
    ]
    assert [row[0].callback_data for row in keyboard.inline_keyboard[:5]] == [
        "addtask_cat:0",
        "addtask_cat:1",
        "addtask_cat:2",
        "addtask_cat:3",
        "addtask_cat:4",
    ]


# --- addtask: entry point ---


@pytest.mark.asyncio
async def test_addtask_start_sends_category_keyboard() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={})

    state = await bot.addtask_start(update, context)

    assert state == bot.ADDTASK_CHOOSING_CATEGORY
    _, kwargs = update.message.reply_text.call_args
    assert len(kwargs["reply_markup"].inline_keyboard) == len(bot.CATEGORIES) + 1


@pytest.mark.asyncio
async def test_addtask_start_blocks_non_admin() -> None:
    update = _non_admin_update(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={})

    result = await bot.addtask_start(update, context)

    assert result is None
    update.message.reply_text.assert_not_called()


# --- addtask: category chosen ---


@pytest.mark.asyncio
async def test_addtask_category_chosen_prompts_for_text_and_swaps_keyboard() -> None:
    query = SimpleNamespace(
        data="addtask_cat:1", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(user_data={}, bot=SimpleNamespace(send_message=AsyncMock()))

    state = await bot.addtask_category_chosen(update, context)

    assert state == bot.ADDTASK_TYPING_TASK
    assert context.user_data["addtask_category"] == bot.CATEGORIES[1]
    query.answer.assert_called_once()

    # The picker message is edited (inline keyboard removed) ...
    _, edit_kwargs = query.edit_message_text.call_args
    assert edit_kwargs["reply_markup"] is None

    # ... and a separate message swaps the persistent keyboard to cancel-only,
    # since Telegram can't attach a ReplyKeyboardMarkup via message editing.
    _, send_kwargs = context.bot.send_message.call_args
    assert [row[0].text for row in send_kwargs["reply_markup"].keyboard] == [
        bot.MENU_CANCEL_LABEL
    ]


@pytest.mark.asyncio
async def test_addtask_category_chosen_cancel_token() -> None:
    query = SimpleNamespace(
        data="addtask_cat:cancel", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_category_chosen(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    query.edit_message_text.assert_called_once_with(
        "Добавление задания отменено.", reply_markup=None
    )


@pytest.mark.asyncio
async def test_addtask_category_chosen_handles_stale_index() -> None:
    query = SimpleNamespace(
        data=f"addtask_cat:{len(bot.CATEGORIES) + 5}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = _admin_update(callback_query=query)
    context = SimpleNamespace(user_data={})

    state = await bot.addtask_category_chosen(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data


# --- addtask: task text received ---


@pytest.mark.asyncio
async def test_addtask_task_received_saves_task_and_restores_menu(
    minimal_state,
) -> None:
    await bot.save_state(minimal_state)

    update = _admin_update(
        message=SimpleNamespace(text="Новое тестовое задание", reply_text=AsyncMock())
    )
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_task_received(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    args, kwargs = update.message.reply_text.call_args
    assert args[0] == "Задание добавлено: #АРТИСТ - Новое тестовое задание"
    assert kwargs["reply_markup"].keyboard[0][0].text == bot.MENU_ADDTASK_LABEL

    saved_state = await bot.load_state()
    assert "Новое тестовое задание" in saved_state["tasks"]["#АРТИСТ"]
    assert "Новое тестовое задание" in saved_state["available"]["#АРТИСТ"]


@pytest.mark.asyncio
async def test_addtask_task_received_rejects_empty_text() -> None:
    update = _admin_update(message=SimpleNamespace(text="   ", reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_task_received(update, context)

    assert state == bot.ADDTASK_TYPING_TASK
    assert context.user_data["addtask_category"] == "#АРТИСТ"


@pytest.mark.asyncio
async def test_addtask_cancel_clears_pending_category_and_restores_menu() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_cancel(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    args, kwargs = update.message.reply_text.call_args
    assert args[0] == "Добавление задания отменено."
    assert kwargs["reply_markup"].keyboard[0][0].text == bot.MENU_ADDTASK_LABEL


# --- addtask: interrupted mid-flow by a different menu button ---


@pytest.mark.asyncio
async def test_addtask_interrupted_by_publish_runs_publish_instead() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_interrupted_by_publish(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    args, _ = update.message.reply_text.call_args
    assert args[0] == "Опубликовать задание сейчас?"


@pytest.mark.asyncio
async def test_addtask_interrupted_by_view_runs_view_instead() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(user_data={"addtask_category": "#АРТИСТ"})

    state = await bot.addtask_interrupted_by_view(update, context)

    assert state == bot.ConversationHandler.END
    assert "addtask_category" not in context.user_data
    args, _ = update.message.reply_text.call_args
    assert args[0] == "Какую категорию показать?"


# --- publish: confirm/cancel button flow ---


@pytest.mark.asyncio
async def test_publish_challenge_cmd_shows_confirmation() -> None:
    update = _admin_update(message=SimpleNamespace(reply_text=AsyncMock()))

    await bot.publish_challenge_cmd(update, SimpleNamespace())

    args, kwargs = update.message.reply_text.call_args
    assert args[0] == "Опубликовать задание сейчас?"
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == ["publish:confirm", "publish:cancel"]


@pytest.mark.asyncio
async def test_publish_confirm_callback_cancel() -> None:
    query = SimpleNamespace(
        data="publish:cancel", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = SimpleNamespace(callback_query=query)

    await bot.publish_confirm_callback(update, SimpleNamespace())

    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once_with("Отменено.", reply_markup=None)


@pytest.mark.asyncio
async def test_publish_confirm_callback_confirm(monkeypatch, mock_application) -> None:
    async def mock_publish(*args, **kwargs):
        return {"category": "#АРТИСТ", "task": "A1"}

    monkeypatch.setattr(bot, "publish_task", mock_publish)

    query = SimpleNamespace(
        data="publish:confirm", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(application=mock_application)

    await bot.publish_confirm_callback(update, context)

    query.edit_message_text.assert_called_once_with(
        "Опубликовано: #АРТИСТ - A1", reply_markup=None
    )


@pytest.mark.asyncio
async def test_publish_confirm_callback_no_tasks_available(
    monkeypatch, mock_application
) -> None:
    async def mock_publish(*args, **kwargs):
        return None

    monkeypatch.setattr(bot, "publish_task", mock_publish)

    query = SimpleNamespace(
        data="publish:confirm", answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(application=mock_application)

    await bot.publish_confirm_callback(update, context)

    query.edit_message_text.assert_called_once_with(
        "Не удалось опубликовать задание (нет доступных заданий).",
        reply_markup=None,
    )
