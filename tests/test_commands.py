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
    update.message.reply_text.assert_called_once_with(
        "Задание опубликовано для испытания."
    )
