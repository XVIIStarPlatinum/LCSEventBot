import asyncio

import pytest

import bot


@pytest.mark.asyncio
async def test_category_rotation(minimal_state) -> None:
    await bot.save_state(minimal_state)

    p1 = await bot.pick_next_task(await bot.load_state())
    assert p1["category"] == "#АРТИСТ"

    p2 = await bot.pick_next_task(await bot.load_state())
    assert p2["category"] == "#БИТМЕЙКЕР"

    p3 = await bot.pick_next_task(await bot.load_state())
    assert p3["category"] == "#ЗВУКОИНЖЕНЕР"


@pytest.mark.asyncio
async def test_no_repeat_within_cycle(minimal_state) -> None:
    await bot.save_state(minimal_state)

    used = set()

    for _ in range(3):
        pick = await bot.pick_next_task(await bot.load_state())
        used.add(pick["task"])

    assert used == {"A1", "B1", "C1"}


@pytest.mark.asyncio
async def test_cycle_reset(minimal_state) -> None:
    await bot.save_state(minimal_state)

    for _ in range(3):
        await bot.pick_next_task(await bot.load_state())

    pick = await bot.pick_next_task(await bot.load_state())
    assert pick["cycle_reset"] is True


@pytest.mark.asyncio
async def test_load_state_cold_start_does_not_deadlock() -> None:
    """
    Регрессионный тест: load_state() раньше вешался навсегда, если
    tasks_state.json ещё не существовал (load_state держал _state_lock
    и одновременно вызывал save_state(), который пытался взять тот же
    non-reentrant Lock повторно). Это и было причиной того, что бот
    зависал на самом первом /addtask или первом запуске на чистом
    окружении -- ровно то, что проявилось в бете, но не в юнит-тестах,
    т.к. все остальные тесты сохраняют состояние до load_state().
    """
    state = await asyncio.wait_for(bot.load_state(), timeout=2)

    assert state["next_category_index"] == 0
    for category in bot.CATEGORIES:
        assert state["tasks"][category] == []
        assert state["available"][category] == []
        assert state["used"][category] == []


@pytest.mark.asyncio
async def test_default_state_tasks_and_available_are_independent() -> None:
    """
    Регрессионный тест: default_state() раньше строил "available" через
    tasks.copy(), что является поверхностной копией -- списки заданий
    для каждой категории оставались ОДНИМ И ТЕМ ЖЕ объектом в "tasks" и
    "available". Из-за этого самое первое /addtask (до появления
    tasks_state.json на диске) дублировало задание в обоих словарях.
    """
    state = bot.default_state()

    for category in bot.CATEGORIES:
        assert state["tasks"][category] is not state["available"][category]

    state["tasks"]["#АРТИСТ"].append("A1")
    state["available"]["#АРТИСТ"].append("A1")

    assert state["tasks"]["#АРТИСТ"] == ["A1"]
    assert state["available"]["#АРТИСТ"] == ["A1"]
