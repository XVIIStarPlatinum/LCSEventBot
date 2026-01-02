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
