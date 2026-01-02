import pytest

import bot


@pytest.mark.asyncio
async def test_publish_task_sends_and_pins(mock_application, minimal_state) -> None:
    await bot.save_state(minimal_state)

    result = await bot.publish_task(mock_application, notify_admin=True)

    assert result is not None
    assert result["category"] == "#АРТИСТ"

    mock_application.bot.send_message.assert_any_call(
        chat_id=bot.GROUP_CHAT_ID,
        text="Еженедельное задание: #АРТИСТ\nA1",
        message_thread_id=bot.TOPIC_ID,
        parse_mode=bot.constants.ParseMode.HTML,
    )
    mock_application.bot.pin_chat_message.assert_called_once()


@pytest.mark.asyncio
async def test_admin_notified_on_publish(mock_application, minimal_state) -> None:
    await bot.save_state(minimal_state)
    await bot.publish_task(mock_application, notify_admin=True)

    mock_application.bot.send_message.assert_any_call(
        chat_id=bot.ADMIN_ID, text="Новое задание опубликовано: #АРТИСТ - A1"
    )


@pytest.mark.asyncio
async def test_cycle_reset_notification(mock_application, minimal_state) -> None:
    await bot.save_state(minimal_state)

    for _ in range(3):
        await bot.publish_task(mock_application)

    await bot.publish_task(mock_application)

    mock_application.bot.send_message.assert_any_call(
        chat_id=bot.ADMIN_ID, text="Все испытания пройдены. Цикл обновлен."
    )
