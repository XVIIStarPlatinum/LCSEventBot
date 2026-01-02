"""
Бот для еженедельного опубликования испытаний в группу
- Опубликуется в понедельниках 00:00 по МСК
- Топик определяется через message_thread_id
- Персистентность обеспечивается путем сохранения задании в tasks_state.json
- В ЛС доступны команды, доступные только админу
"""

import asyncio
import json
import logging
import os
import random
from typing import Any, Dict

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))
STATE_FILE = os.getenv("STATE_FILE", "tasks_state.json")

CATEGORIES = ["#АРТИСТ", "#БИТМЕЙКЕР", "#ЗВУКОИНЖЕНЕР"]

TIMEZONE = pytz.timezone("Europe/Moscow")

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def default_state() -> dict[str, dict[str, list[Any]] | int]:
    """
    Структура JSON-файла с испытаниями:
    {
        "tasks": {
            category1: [task1, task2, ...],
            category2: [task3, task4, ...],
            ...
        },
        "available": {
            category1: [task1, task2, ...],
            category2: [task3, task4, ...],
            ...
        },
        "used": {
            category1: [task1, task2, ...],
            category2: [task3, task4, ...],
            ...
        },
        "next_category_index": 0
    }
    Returns:
        Dict: Словарь с ключом и значением.
        Может быть либо строкой, вложенным словарем или числом (индекс).
    """
    tasks = {c: [] for c in CATEGORIES}
    return {
        "tasks": tasks,
        "available": tasks.copy(),
        "used": {c: [] for c in CATEGORIES},
        "next_category_index": 0,
    }


_state_lock = asyncio.Lock()


async def load_state() -> Dict[str, dict[str, list[Any]] | int]:
    """
    Загружает испытания в контекст бота.
    Если файла нет, то создает новую на основе
    предопределенной в default_state() структуры.
    Returns:
        Dict: Словарь с испытаниями.
    """
    async with _state_lock:
        if not os.path.exists(STATE_FILE):
            state = default_state()
            await save_state(state)
            return state
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        for key in ("tasks", "available", "used"):
            if key not in state:
                state[key] = {c: [] for c in CATEGORIES}
        if "next_category_index" not in state:
            state["next_category_index"] = 0
        return state


async def save_state(state: Dict[str, dict[str, list[Any]] | int]) -> None:
    """
    Сохраняет испытания, загруженную из load_state(), в контекст бота.
    Args:
        state (Dict[str, dict[str, list[Any]] | int]): Словарь с испытаниями.
    """
    async with _state_lock:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


async def pick_next_task(
    state: Dict[str, dict[str, list[Any]] | int],
) -> dict[str, bool | None] | None:
    """
    Случайным образом выбирается следующее задание для опубликования.
    Args:
        state (Dict): состояние задания в виде словаря до выбора
    Returns:
        dict: выбранное задание
    """
    start_idx = state.get("next_category_index", 0) % len(CATEGORIES)
    idx = start_idx

    searched = 0
    while (
        searched < len(CATEGORIES)
        and len(state["available"].get(CATEGORIES[idx], [])) == 0
    ):
        idx = (idx + 1) % len(CATEGORIES)
        searched += 1

    if searched >= len(CATEGORIES):
        for c in CATEGORIES:
            used = state["used"].get(c, [])
            state["available"][c] = state["available"].get(c, []) + used
            state["used"][c] = []
        await save_state(state)
        return {"category": None, "task": None, "cycle_reset": True}

    category = CATEGORIES[idx]
    task_list = state["available"][category]
    task = random.choice(task_list)

    task_list.remove(task)
    state["used"].setdefault(category, []).append(task)
    state["next_category_index"] = (idx + 1) % len(CATEGORIES)

    await save_state(state)
    return {"category": category, "task": task, "cycle_reset": False}


def admin_only(func):
    """
    С помощью этого декоратора определяются
    функциональности, доступные только админу.
    :param func: функция
    """

    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        user = update.effective_user
        if not user or user.id != ADMIN_ID or update.effective_chat.type != "private":
            logger.warning(
                "Попытка доступа от лица, " + "не являющийся админом, заблокирована."
            )
            return None
        return await func(update, context, *args, **kwargs)

    return wrapper


@admin_only
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ответ на /start.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    await update.message.reply_text("Бот запущен и готов публиковать задания.")


@admin_only
async def addtask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ответ на /addtask.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """

    text = update.message.text or ""
    parts = []
    cur = ""
    in_quotes = False
    for ch in text[text.find(" ") + 1 :]:
        if ch == '"':
            in_quotes = not in_quotes
            if not in_quotes:
                parts.append(cur.strip())
                cur = ""
            continue
        if in_quotes:
            cur += ch
    if len(parts) > 2:
        await update.message.reply_text(
            'Usage: /addtask "хэштег" "текст задания"\n'
            + 'Example: /addtask "#АРТИСТ" "Запишите короткую песню на 60 сек."'
        )
        return
    hashtag = parts[0]
    task_text = parts[1]

    if hashtag not in CATEGORIES:
        await update.message.reply_text(
            "Неопознанная категория. " + f"Разрешены только: {', '.join(CATEGORIES)}"
        )
        return

    state = await load_state()
    state["tasks"].setdefault(hashtag, []).append(task_text)
    state["available"].setdefault(hashtag, []).append(task_text)
    await save_state(state)

    await update.message.reply_text(f"Задание добавлено: {hashtag} - {task_text}")


async def publish_task(application, notify_admin: bool = True):
    """
    Эта функция отвечает за публикацию заданий.
    Можно напрямую, можно и автоматически через заданный срок.
    Args:
        application (Application): контекст приложения
        notify_admin (bool): надо ли оповещать админа?
    """
    logger.info("publish_task: Запущен процесс опубликования задания...")

    state = await load_state()
    pick = await pick_next_task(state)
    if pick["cycle_reset"]:
        logger.info("publish_task: Все задания были опубликованы до этого.")
        if notify_admin:
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_ID, text="Все испытания пройдены. Цикл обновлен."
                )
            except Exception as e:
                logger.exception(
                    "publish_task: не удалось оповестить"
                    + " админа про обновления цикла: %s",
                    e,
                )
            state = await load_state()
            pick = await pick_next_task(state)
            if pick["cycle_reset"]:
                await application.bot.send_message(
                    chat_id=ADMIN_ID, text="Нет задания, которых можно опубликовать."
                )
            return None

    full_text = f"Еженедельное задание: {pick['category']}\n{pick['task']}"
    try:
        sent_msg = await application.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=full_text,
            message_thread_id=TOPIC_ID,
            parse_mode=constants.ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(
            "publish_task: не удалось" + " отправить сообщение в группу: %s", e
        )

    try:
        await application.bot.pin_chat_message(
            chat_id=GROUP_CHAT_ID,
            message_id=sent_msg.message_id,
            disable_notification=True,
        )
    except Exception as e:
        logger.exception(
            "publish_task: не удалось" + " закрепить сообщение с испытанием: %s", e
        )

    if notify_admin:
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text="Новое задание опубликовано: "
                + f"{pick['category']} - {pick['task']}",
            )
        except Exception as e:
            logger.exception(
                "publish_task: не удалось оповестить админа"
                + " про опубликования задания в группу: %s",
                e,
            )

    logger.info("publish_task: процесс завершен")
    return {"category": pick["category"], "task": pick["task"], "message": sent_msg}


@admin_only
async def publish_challenge_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отвечает на publish.
    Публикует задания напрямую вне зависимости от расписания.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    application = context.application
    result = await publish_task(application, notify_admin=True)
    if result is None:
        await update.message.reply_text(
            "Не удалось опубликовать задание (нет доступных заданий)."
        )
        return
    await update.message.reply_text("Задание опубликовано для испытания.")


async def publish_weekly_job(application: Application):
    """
    Отвечает за автоматический вызов публикации испытания.
    Задача на cron вызывает эту функцию, который вызывает опубликования.
    Args:
        application (Application): Контекст приложения.
    """
    logger.info("Выполняется процесс по расписанию...")
    result = await publish_task(application, notify_admin=True)
    if result is None:
        logger.warning("publish_weekly_job: Задание не было опубликовано.")


async def main():
    if BOT_TOKEN is None or BOT_TOKEN == "" or BOT_TOKEN.startswith("..."):
        raise RuntimeError(
            "Установите переменную окружения BOT_TOKEN"
            + " или отредактируйте код, чтобы включилось токен бота."
        )
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("addtask", addtask_cmd))
    application.add_handler(CommandHandler("publish", publish_challenge_cmd))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    trigger = CronTrigger(day_of_week="mon", hour=0, minute=0, timezone=TIMEZONE)
    scheduler.add_job(
        lambda: asyncio.create_task(publish_weekly_job(application)),
        trigger=trigger,
        id="weekly_publish",
    )
    scheduler.start()
    logger.info("Планировщик задач запущено")

    await application.initialize()
    await application.start()
    logger.info("Бот запущен.")

    await application.updater.start_polling()
    try:
        await application.updater.idle()
    finally:
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
