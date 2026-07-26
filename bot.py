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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()


def _require_int_env(name: str) -> int:
    """
    Читает обязательную переменную окружения и приводит её к int.
    Бросает понятную ошибку вместо TypeError, если переменная не задана
    или задана некорректно.
    """
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Установите переменную окружения {name}")
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(
            f"Переменная окружения {name} должна быть целым числом, получено: {value!r}"
        )


BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = _require_int_env("ADMIN_ID")
GROUP_CHAT_ID = _require_int_env("GROUP_CHAT_ID")
TOPIC_ID = _require_int_env("TOPIC_ID")
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
    return {
        "tasks": {c: [] for c in CATEGORIES},
        "available": {c: [] for c in CATEGORIES},
        "used": {c: [] for c in CATEGORIES},
        "next_category_index": 0,
    }


_state_lock = asyncio.Lock()


def _write_state_to_disk(state: Dict[str, dict[str, list[Any]] | int]) -> None:
    """
    Записывает состояние на диск. Не берёт _state_lock сама —
    вызывающий код обязан уже держать блокировку.
    """
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


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
            _write_state_to_disk(state)
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
        _write_state_to_disk(state)


async def pick_next_task(
    state: Dict[str, dict[str, list[Any]] | int],
) -> dict[str, bool | None] | dict[str, str | bool | Any]:
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
        chat = update.effective_chat
        if not user or not chat or chat.type != "private" or user.id != ADMIN_ID:
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
    await update.message.reply_text("Бот запущен и готов публиковать задания!")


async def _add_task(category: str, task_text: str) -> None:
    """
    Общая логика добавления задания в состояние: используется как
    старым, так и новым (кнопочным) способом добавления заданий.
    Args:
        category (str): категория (хэштег), должна быть одной из CATEGORIES.
        task_text (str): текст задания.
    """
    state = await load_state()
    state["tasks"].setdefault(category, []).append(task_text)
    state["available"].setdefault(category, []).append(task_text)
    await save_state(state)


def _build_category_keyboard() -> InlineKeyboardMarkup:
    """
    Строит клавиатуру с одной кнопкой на каждую категорию из CATEGORIES.
    Масштабируется автоматически: 2, 5 или любое другое число категорий
    -- достаточно отредактировать список CATEGORIES, без изменений кода
    самой клавиатуры или обработчиков.
    callback_data кодирует индекс категории (а не сам хэштег), чтобы не
    зависеть от длины/кодировки названия категории и не упираться в
    64-байтный лимит callback_data у Telegram.
    """
    buttons = [
        [InlineKeyboardButton(category, callback_data=f"addtask_cat:{i}")]
        for i, category in enumerate(CATEGORIES)
    ]
    return InlineKeyboardMarkup(buttons)


# Состояния ConversationHandler для /addtask.
ADDTASK_CHOOSING_CATEGORY, ADDTASK_TYPING_TASK = range(2)


@admin_only
async def addtask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Точка входа в /addtask: показывает кнопки с категориями.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    await update.message.reply_text(
        "Выберите категорию для нового задания:",
        reply_markup=_build_category_keyboard(),
    )
    return ADDTASK_CHOOSING_CATEGORY


@admin_only
async def addtask_category_chosen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Обрабатывает нажатие на кнопку с категорией и просит прислать текст задания.
    Args:
        update (Update): Событие обновления состояния (CallbackQuery).
        context (ContextTypes): Контекст приложения.
    """
    query = update.callback_query
    await query.answer()

    _, index_str = query.data.split(":", 1)
    index = int(index_str)

    if index < 0 or index >= len(CATEGORIES):
        await query.edit_message_text(
            "Категория больше не существует. Начните заново командой /addtask.",
            reply_markup=None,
        )
        return ConversationHandler.END

    category = CATEGORIES[index]
    context.user_data["addtask_category"] = category

    await query.edit_message_text(
        f"Категория: {category}\nТеперь пришлите текст задания одним сообщением.\n"
        "Либо /cancel для отмены.",
        reply_markup=None,
    )
    return ADDTASK_TYPING_TASK


@admin_only
async def addtask_task_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Получает текст задания, сохраняет его в выбранную ранее категорию.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    category = context.user_data.pop("addtask_category", None)
    if category is None:
        await update.message.reply_text(
            "Что-то пошло не так, начните заново командой /addtask."
        )
        return ConversationHandler.END

    task_text = (update.message.text or "").strip()
    if not task_text:
        context.user_data["addtask_category"] = category
        await update.message.reply_text(
            "Текст задания не может быть пустым. Пришлите текст ещё раз, "
            "либо /cancel для отмены."
        )
        return ADDTASK_TYPING_TASK

    await _add_task(category, task_text)
    await update.message.reply_text(f"Задание добавлено: {category} - {task_text}")
    return ConversationHandler.END


@admin_only
async def addtask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Прерывает диалог добавления задания.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    context.user_data.pop("addtask_category", None)
    await update.message.reply_text("Добавление задания отменено.")
    return ConversationHandler.END


addtask_conversation = ConversationHandler(
    entry_points=[CommandHandler("addtask", addtask_start)],
    states={
        ADDTASK_CHOOSING_CATEGORY: [
            CallbackQueryHandler(addtask_category_chosen, pattern=r"^addtask_cat:\d+$")
        ],
        ADDTASK_TYPING_TASK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_task_received)
        ],
    },
    fallbacks=[CommandHandler("cancel", addtask_cancel)],
    # per_message=False (по умолчанию) намеренно: этот диалог смешивает
    # CommandHandler/MessageHandler с CallbackQueryHandler, а per_message=True
    # имеет смысл только если ВСЕ обработчики состояний -- CallbackQueryHandler.
    # PTBUserWarning про "not tracked for every message" в данном случае ожидаем
    # и безопасен: только один админ, один диалог за раз.
    per_message=False,
)


# Сериализует вызовы publish_task(), чтобы избежать двойной публикации
# при одновременных ручном /publish и запуске по расписанию.
_publish_lock = asyncio.Lock()


async def publish_task(application, notify_admin: bool = True):
    """
    Эта функция отвечает за публикацию заданий.
    Можно напрямую, можно и автоматически через заданный срок.

    ВАЖНО: Использует _publish_lock для предотвращения race conditions
    при одновременных вызовах публикации.

    Args:
        application (Application): контекст приложения
        notify_admin (bool): надо ли оповещать админа?
    """
    # Критическая секция: вся логика от load до save должна быть атомарной
    async with _publish_lock:
        logger.info("publish_task: Запущен процесс опубликования задания...")

        state = await load_state()
        pick = await pick_next_task(state)

        if pick["cycle_reset"]:
            logger.info("publish_task: Цикл обновлен, ищем задание заново...")
            if notify_admin:
                try:
                    await application.bot.send_message(
                        chat_id=ADMIN_ID, text="Все испытания пройдены. Цикл обновлён."
                    )
                except Exception as e:
                    logger.error(f"Не удалось оповестить админа: {e}")

            state = await load_state()
            pick = await pick_next_task(state)

            if pick["cycle_reset"]:
                if notify_admin:
                    try:
                        await application.bot.send_message(
                            chat_id=ADMIN_ID, text="Заданий для публикации нет."
                        )
                    except Exception as e:
                        logger.error(f"Не удалось оповестить админа: {e}")
                return None

        # Публикация происходит вне критической секции для state,
        # но внутри _publish_lock для сериализации публикаций
        full_text = f"Еженедельное задание: {pick['category']}\n{pick['task']}"
        sent_msg = None

        try:
            sent_msg = await application.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=full_text,
                message_thread_id=TOPIC_ID,
            )
            logger.info("Сообщение успешно отправлено")

            if sent_msg:
                await application.bot.pin_chat_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=sent_msg.message_id,
                    disable_notification=True,
                )
                logger.info("Сообщение закреплено")

        except Exception as e:
            logger.exception(f"Критическая ошибка при публикации в группу: {e}")
            if not sent_msg:
                return None

        if notify_admin:
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"Новое задание опубликовано: {pick['category']} - {pick['task']}",
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить отчет админу: {e}")

        logger.info("publish_task: процесс успешно завершен")
        return {"category": pick["category"], "task": pick["task"], "message": sent_msg}


@admin_only
async def publish_challenge_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data="publish:confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="publish:cancel"),
        ]
    ])
    await update.message.reply_text(
        "Опубликовать задание сейчас?", reply_markup=keyboard
    )


async def publish_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # clears the loading spinner — do this FIRST, before any slow work

    if query.data == "publish:cancel":
        await query.edit_message_text("Отменено.", reply_markup=None)
        return

    application = context.application
    result = await publish_task(application, notify_admin=True)

    if result is None:
        await query.edit_message_text(
            "Не удалось опубликовать задание (нет доступных заданий).",
            reply_markup=None,
        )
        return

    await query.edit_message_text(
        f"Опубликовано: {result['category']} - {result['task']}",
        reply_markup=None,
    )


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
    if not BOT_TOKEN or BOT_TOKEN.startswith("..."):
        raise RuntimeError("Установите переменную окружения BOT_TOKEN")

    while True:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_cmd))
        application.add_handler(addtask_conversation)
        application.add_handler(CommandHandler("publish", publish_challenge_cmd))
        application.add_handler(CallbackQueryHandler(publish_confirm_callback, pattern="^publish:"))

        try:
            await application.initialize()
            await application.bot.delete_webhook(drop_pending_updates=True)
            await application.start()

            scheduler = AsyncIOScheduler(timezone=TIMEZONE)
            scheduler.add_job(
                lambda: asyncio.create_task(publish_weekly_job(application)),
                CronTrigger(day_of_week="mon", hour=0, minute=0, timezone=TIMEZONE),
                id="weekly_publish",
            )
            scheduler.start()

            await application.updater.start_polling()

            while application.updater.running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Связь утеряна: {e}")
        finally:
            if "scheduler" in locals() and scheduler.running:
                scheduler.shutdown()

            if application.running:
                if application.updater.running:
                    await application.updater.stop()
                await application.stop()

            await application.shutdown()

            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
