import pathlib
import sys
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

import bot

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """
    Данная фикстура обеспечивает,
    чтобы использовались переменные файлы для каждого теста.
    Args:
        tmp_path: путь переменного файла
        monkeypatch: эквивалент рефлексии в Java, я хз)
    """
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(bot, "STATE_FILE", str(state_file))


@pytest.fixture
def minimal_state() -> Dict[str, dict[str, list[Any]] | int]:
    """
    Минимальный набор состояния.
    Returns:
        Dict[str, dict[str, list[Any]] | int]: Минимальный набор состояния.
    """
    return {
        "tasks": {"#АРТИСТ": ["A1"], "#БИТМЕЙКЕР": ["B1"], "#ЗВУКОИНЖЕНЕР": ["C1"]},
        "available": {"#АРТИСТ": ["A1"], "#БИТМЕЙКЕР": ["B1"], "#ЗВУКОИНЖЕНЕР": ["C1"]},
        "used": {"#АРТИСТ": [], "#БИТМЕЙКЕР": [], "#ЗВУКОИНЖЕНЕР": []},
        "next_category_index": 0,
    }


@pytest.fixture
async def mock_application():
    """
    Замоканное приложение.
    Returns:
        SimpleNamespace: пространство имен
    """
    mock_bot = SimpleNamespace(
        send_message=AsyncMock(),
        pin_chat_message=AsyncMock(),
    )
    return SimpleNamespace(bot=mock_bot)
