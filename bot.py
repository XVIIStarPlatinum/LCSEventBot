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
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
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
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Moscow"))

CATEGORIES = ["#АРТИСТ", "#БИТМЕЙКЕР", "#ЗВУКОИНЖЕНЕР"]


# Подписи кнопок постоянного меню (ReplyKeyboardMarkup)
# К самому наиогромнейшему сожалению, избавиться от /start никак
MENU_ADDTASK_LABEL = "➕ Добавить задание"
MENU_PUBLISH_LABEL = "📢 Опубликовать"
MENU_VIEW_LABEL = "📋 Список заданий"
MENU_CANCEL_LABEL = "❌ Отмена"


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Постоянная клавиатура главного меню -- показывается всегда, когда
    админ не находится внутри диалога добавления задания.
    """
    return ReplyKeyboardMarkup(
        [[MENU_ADDTASK_LABEL], [MENU_PUBLISH_LABEL], [MENU_VIEW_LABEL]],
        resize_keyboard=True,
    )


def _cancel_only_keyboard() -> ReplyKeyboardMarkup:
    """
    Временная клавиатура с одной кнопкой отмены -- показывается, пока
    бот ждёт от админа текст задания (свободный текст, поэтому обычное
    меню в этот момент только мешало бы).
    """
    return ReplyKeyboardMarkup([[MENU_CANCEL_LABEL]], resize_keyboard=True)


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
    Ответ на /start. Это единственная слэш-команда, которая остаётся --
    Telegram требует хотя бы одно сообщение от пользователя, чтобы открыть
    чат с ботом впервые, и сам показывает нативную кнопку "Start" для этого.
    После неё вся навигация идёт через кнопки постоянного меню.
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    await update.message.reply_text(
        "Бот запущен и готов публиковать задания!",
        reply_markup=_main_menu_keyboard(),
    )


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
    buttons.append(
        [InlineKeyboardButton(MENU_CANCEL_LABEL, callback_data="addtask_cat:cancel")]
    )
    return InlineKeyboardMarkup(buttons)


# Состояния ConversationHandler для потока "Добавить задание".
ADDTASK_CHOOSING_CATEGORY, ADDTASK_TYPING_TASK = range(2)


@admin_only
async def addtask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Точка входа в поток "Добавить задание": показывает кнопки с категориями.
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
    Обрабатывает нажатие на кнопку с категорией (или отмену) и просит
    прислать текст задания.
    Args:
        update (Update): Событие обновления состояния (CallbackQuery).
        context (ContextTypes): Контекст приложения.
    """
    query = update.callback_query
    await query.answer()

    _, token = query.data.split(":", 1)

    if token == "cancel":
        context.user_data.pop("addtask_category", None)
        await query.edit_message_text("Добавление задания отменено.", reply_markup=None)
        return ConversationHandler.END

    index = int(token)

    if index < 0 or index >= len(CATEGORIES):
        await query.edit_message_text(
            "Категория больше не существует. Начните заново, нажав "
            f'"{MENU_ADDTASK_LABEL}".',
            reply_markup=None,
        )
        return ConversationHandler.END

    category = CATEGORIES[index]
    context.user_data["addtask_category"] = category

    await query.edit_message_text(f"Категория: {category}", reply_markup=None)
    # ReplyKeyboardMarkup нельзя прикрепить к edit_message_text -- Telegram
    # поддерживает только один тип разметки за раз, и редактирование
    # существующего сообщения принимает лишь InlineKeyboardMarkup. Поэтому
    # смена постоянной клавиатуры на "только отмена" -- отдельным сообщением.
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Пришлите текст задания одним сообщением.",
        reply_markup=_cancel_only_keyboard(),
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
            "Что-то пошло не так, начните заново, нажав " f'"{MENU_ADDTASK_LABEL}".',
            reply_markup=_main_menu_keyboard(),
        )
        return ConversationHandler.END

    task_text = (update.message.text or "").strip()
    if not task_text:
        context.user_data["addtask_category"] = category
        await update.message.reply_text(
            "Текст задания не может быть пустым. Пришлите текст ещё раз, "
            f'либо нажмите "{MENU_CANCEL_LABEL}".'
        )
        return ADDTASK_TYPING_TASK

    await _add_task(category, task_text)
    await update.message.reply_text(
        f"Задание добавлено: {category} - {task_text}",
        reply_markup=_main_menu_keyboard(),
    )
    return ConversationHandler.END


@admin_only
async def addtask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Прерывает диалог добавления задания (нажатие "Отмена" во время ввода текста).
    Args:
        update (Update): Событие обновления состояния.
        context (ContextTypes): Контекст приложения.
    """
    context.user_data.pop("addtask_category", None)
    await update.message.reply_text(
        "Добавление задания отменено.", reply_markup=_main_menu_keyboard()
    )
    return ConversationHandler.END


@admin_only
async def addtask_interrupted_by_publish(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Админ нажал "Опубликовать" вместо выбора категории -- прерываем
    добавление задания и сразу выполняем то, что он нажал.
    """
    context.user_data.pop("addtask_category", None)
    await publish_challenge_cmd(update, context)
    return ConversationHandler.END


@admin_only
async def addtask_interrupted_by_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Админ нажал "Список заданий" вместо выбора категории -- прерываем
    добавление задания и сразу выполняем то, что он нажал.
    """
    context.user_data.pop("addtask_category", None)
    await view_start(update, context)
    return ConversationHandler.END


addtask_conversation = ConversationHandler(
    entry_points=[MessageHandler(filters.Text([MENU_ADDTASK_LABEL]), addtask_start)],
    states={
        ADDTASK_CHOOSING_CATEGORY: [
            CallbackQueryHandler(
                addtask_category_chosen, pattern=r"^addtask_cat:(\d+|cancel)$"
            )
        ],
        ADDTASK_TYPING_TASK: [
            MessageHandler(filters.Text([MENU_CANCEL_LABEL]), addtask_cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_task_received),
        ],
    },
    fallbacks=[
        # Покрывает случай, когда админ всё ещё видит обычное меню
        # (клавиатура ещё не переключилась на "только отмена") на шаге
        # выбора категории и жмёт другую кнопку меню вместо категории.
        MessageHandler(
            filters.Text([MENU_PUBLISH_LABEL]), addtask_interrupted_by_publish
        ),
        MessageHandler(filters.Text([MENU_VIEW_LABEL]), addtask_interrupted_by_view),
        MessageHandler(filters.Text([MENU_ADDTASK_LABEL]), addtask_start),
    ],
    # per_message=False (по умолчанию) намеренно: этот диалог смешивает
    # MessageHandler с CallbackQueryHandler, а per_message=True
    # имеет смысл только если *все* обработчики состояний -- CallbackQueryHandler.
    # PTBUserWarning про "not tracked for every message" в данном случае ожидаем
    # и безопасен.
    per_message=False,
)


# --- Просмотр списка заданий (доступные / использованные / все) ---

POOL_LABELS = {
    "tasks": "Все",
    "available": "Доступные",
    "used": "Использованные",
}

TELEGRAM_MESSAGE_LIMIT = 4096
# Запас под случаи, когда Telegram вдруг потроллить (эмодзи и т.п.)
_SAFE_CHUNK_SIZE = TELEGRAM_MESSAGE_LIMIT - 200


def _build_view_category_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора категории для просмотра: одна кнопка на каждую
    категорию из CATEGORIES (масштабируется автоматически, как и в
    "Добавить задание") плюс кнопка "ВСЕ" для агрегированного просмотра.
    """
    buttons = [
        [InlineKeyboardButton(category, callback_data=f"viewcat:{i}")]
        for i, category in enumerate(CATEGORIES)
    ]
    buttons.append([InlineKeyboardButton("ВСЕ", callback_data="viewcat:all")])
    return InlineKeyboardMarkup(buttons)


def _build_view_pool_keyboard(cat_token: str) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора списка (все / доступные / использованные) для уже
    выбранной категории (или "ВСЕ"). cat_token переносится в callback_data,
    чтобы не хранить промежуточное состояние отдельно.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📋 Все", callback_data=f"viewpool:{cat_token}:tasks"
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Доступные", callback_data=f"viewpool:{cat_token}:available"
                )
            ],
            [
                InlineKeyboardButton(
                    "☑️ Использованные", callback_data=f"viewpool:{cat_token}:used"
                )
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="viewback")],
        ]
    )


def _category_label(cat_token: str) -> str:
    if cat_token == "all":
        return "ВСЕ"
    return CATEGORIES[int(cat_token)]


def _format_task_list(category: str, pool_name: str, items: list) -> str:
    """
    Форматирует список заданий одной категории. Порядок -- как в
    состоянии (т.е. в порядке добавления: элементы только добавляются
    через append и убираются через remove, порядок остальных не меняется).
    """
    header = f"{category} — {POOL_LABELS[pool_name]} ({len(items)})"
    if not items:
        return f"{header}\nСписок пуст."
    body = "\n".join(f"{i}. {task}" for i, task in enumerate(items, start=1))
    return f"{header}\n{body}"


def _format_all_categories(pool_name: str, state: dict) -> str:
    sections = [
        _format_task_list(category, pool_name, state[pool_name].get(category, []))
        for category in CATEGORIES
    ]
    return f"ВСЕ категории — {POOL_LABELS[pool_name]}:\n\n" + "\n\n".join(sections)


async def _send_long_text(bot_api, chat_id: int, text: str, reply_markup=None) -> None:
    """
    Отправляет текст одним сообщением, либо, если он превышает лимит
    Telegram (4096 символов), разбивает его на несколько сообщений по
    границам строк. reply_markup прикрепляется только к последнему чанку.
    """
    if len(text) <= _SAFE_CHUNK_SIZE:
        await bot_api.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        return

    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > _SAFE_CHUNK_SIZE:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        await bot_api.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=reply_markup if is_last else None,
        )


@admin_only
async def view_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Точка входа в просмотр заданий: показывает кнопки с категориями.
    """
    await update.message.reply_text(
        "Какую категорию показать?", reply_markup=_build_view_category_keyboard()
    )


@admin_only
async def view_category_chosen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Обрабатывает выбор категории (или "ВСЕ") и предлагает выбрать список.
    """
    query = update.callback_query
    await query.answer()

    _, cat_token = query.data.split(":", 1)
    label = _category_label(cat_token)

    await query.edit_message_text(
        f"Категория: {label}\nКакой список показать?",
        reply_markup=_build_view_pool_keyboard(cat_token),
    )


@admin_only
async def view_back_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Возвращает от выбора списка обратно к выбору категории.
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Какую категорию показать?", reply_markup=_build_view_category_keyboard()
    )


@admin_only
async def view_pool_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает выбор списка (все / доступные / использованные) и
    выводит итоговый список заданий, при необходимости разбивая его на
    несколько сообщений.
    """
    query = update.callback_query
    await query.answer()

    _, cat_token, pool_name = query.data.split(":", 2)
    state = await load_state()

    if cat_token == "all":
        text = _format_all_categories(pool_name, state)
    else:
        category = CATEGORIES[int(cat_token)]
        text = _format_task_list(
            category, pool_name, state[pool_name].get(category, [])
        )

    await query.edit_message_text("Список ниже 👇", reply_markup=None)

    again_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Посмотреть ещё", callback_data="view_again")]]
    )
    await _send_long_text(
        context.bot, update.effective_chat.id, text, reply_markup=again_keyboard
    )


@admin_only
async def view_again_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Повторно показывает выбор категории после того, как итоговый список
    уже был выведен (сам список мог быть в нескольких сообщениях, поэтому
    проще прислать новое сообщение, чем редактировать старое).
    """
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Какую категорию показать?",
        reply_markup=_build_view_category_keyboard(),
    )


# Сериализует вызовы publish_task(), чтобы избежать двойной публикации
# при одновременных ручной публикации ("Опубликовать") и запуске по расписанию.
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
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Опубликовать", callback_data="publish:confirm"
                ),
                InlineKeyboardButton("❌ Отмена", callback_data="publish:cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "Опубликовать задание сейчас?", reply_markup=keyboard
    )


async def publish_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Очищает спинер крч
    await query.answer()

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
        # addtask_conversation должен быть зарегистрирован ДО обычных
        # обработчиков кнопок меню ниже: пока диалог активен, он должен
        # первым перехватывать нажатия "Опубликовать"/"Список заданий"
        # (через свои fallbacks) и решать, что с ними делать. Если бы
        # порядок был обратный, эти нажатия перехватывались бы в обход
        # диалога, и context.user_data["addtask_category"] мог бы повиснуть.
        application.add_handler(addtask_conversation)
        application.add_handler(
            MessageHandler(filters.Text([MENU_PUBLISH_LABEL]), publish_challenge_cmd)
        )
        application.add_handler(
            MessageHandler(filters.Text([MENU_VIEW_LABEL]), view_start)
        )
        application.add_handler(
            CallbackQueryHandler(publish_confirm_callback, pattern="^publish:")
        )
        application.add_handler(
            CallbackQueryHandler(view_category_chosen, pattern=r"^viewcat:(\d+|all)$")
        )
        application.add_handler(
            CallbackQueryHandler(view_back_chosen, pattern=r"^viewback$")
        )
        application.add_handler(
            CallbackQueryHandler(view_pool_chosen, pattern=r"^viewpool:")
        )
        application.add_handler(
            CallbackQueryHandler(view_again_chosen, pattern=r"^view_again$")
        )

        try:
            await application.initialize()
            await application.bot.delete_webhook(drop_pending_updates=True)
            await application.start()

            scheduler = AsyncIOScheduler(timezone=TIMEZONE)
            scheduler.add_job(
                publish_weekly_job,
                'cron',
                day_of_week='mon',
                hour=0,
                minute=0,
                args=[application]
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
