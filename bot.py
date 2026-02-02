import re
import logging
import telebot
import os
import openai
import json
import boto3
import time
import threading
import base64
import requests
import asyncio
import uuid
import tempfile
from datetime import datetime
from telebot.types import InputFile
from dotenv import load_dotenv
from collections import defaultdict

# Загрузка переменных окружения из .env
load_dotenv()

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
S3_KEY_ID = os.environ.get("S3_KEY_ID")
S3_KEY_SECRET = os.environ.get("S3_KEY_SECRET")
S3_BUCKET = os.environ.get("S3_BUCKET")

from telebot import types
import html as html_module

def escape_html(text):
    """Экранирует HTML спецсимволы"""
    if not text:
        return ""
    return html_module.escape(str(text))

def markdown_to_html(text):
    """
    Конвертирует Markdown в Telegram HTML.
    Поддерживает: **bold**, *italic*, `code`, ```code blocks```, [links](url),
    ~~strikethrough~~, заголовки (#), списки (-)

    Обрабатывает форматирование в правильном порядке, чтобы избежать конфликтов.
    """
    if not text:
        return ""

    # Сохраняем code blocks и inline code, заменяя их на плейсхолдеры
    code_blocks = []
    inline_codes = []

    # Code blocks (```...```) - используем \x00 как маркер, чтобы избежать конфликтов
    def save_code_block(match):
        code = match.group(1)
        placeholder = f"\x00CODEBLOCK\x00{len(code_blocks)}\x00"
        code_blocks.append(f'<pre>{escape_html(code)}</pre>')
        return placeholder

    result = re.sub(r'```(.*?)```', save_code_block, text, flags=re.DOTALL)

    # Inline code (`...`)
    def save_inline_code(match):
        code = match.group(1)
        placeholder = f"\x00INLINECODE\x00{len(inline_codes)}\x00"
        inline_codes.append(f'<code>{escape_html(code)}</code>')
        return placeholder

    result = re.sub(r'`([^`]+)`', save_inline_code, result)

    # Экранируем HTML спецсимволы в обычном тексте
    result = escape_html(result)

    # Восстанавливаем плейсхолдеры (они уже экранированы, но нам нужны оригинальные)
    for i in range(len(code_blocks)):
        result = result.replace(escape_html(f"\x00CODEBLOCK\x00{i}\x00"), f"\x00CODEBLOCK\x00{i}\x00")
    for i in range(len(inline_codes)):
        result = result.replace(escape_html(f"\x00INLINECODE\x00{i}\x00"), f"\x00INLINECODE\x00{i}\x00")

    # Теперь обрабатываем остальное форматирование (текст уже экранирован)

    # Заголовки (### Header) - конвертируем в bold с переносами
    # H1: # Header → <b>📌 Header</b>
    result = re.sub(r'^# (.+)$', r'<b>📌 \1</b>', result, flags=re.MULTILINE)
    # H2: ## Header → <b>▸ Header</b>
    result = re.sub(r'^## (.+)$', r'<b>▸ \1</b>', result, flags=re.MULTILINE)
    # H3: ### Header → <b>• \1</b>
    result = re.sub(r'^### (.+)$', r'<b>• \1</b>', result, flags=re.MULTILINE)
    # H4-H6: просто bold
    result = re.sub(r'^#{4,6} (.+)$', r'<b>\1</b>', result, flags=re.MULTILINE)

    # Списки (- item или * item) - добавляем bullet point
    result = re.sub(r'^[\-\*] (.+)$', r'  • \1', result, flags=re.MULTILINE)
    # Нумерованные списки (1. item)
    result = re.sub(r'^(\d+)\. (.+)$', r'  \1. \2', result, flags=re.MULTILINE)

    # Links [text](url) - обрабатываем до bold/italic
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2)
        return f'<a href="{url}">{link_text}</a>'
    result = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, result)

    # Bold (**text**) - используем non-greedy match
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)

    # Italic (*text*) - только одиночные звездочки, не жадный match
    result = re.sub(r'(?<!\*)\*(?!\*)(.+?)\*(?!\*)', r'<i>\1</i>', result)

    # Strikethrough (~~text~~)
    result = re.sub(r'~~(.+?)~~', r'<s>\1</s>', result)

    # Underline (__text__)
    result = re.sub(r'__(.+?)__', r'<u>\1</u>', result)

    # Восстанавливаем code blocks
    for i, code_html in enumerate(code_blocks):
        result = result.replace(f"\x00CODEBLOCK\x00{i}\x00", code_html)

    # Восстанавливаем inline code
    for i, code_html in enumerate(inline_codes):
        result = result.replace(f"\x00INLINECODE\x00{i}\x00", code_html)

    return result

def escape_markdown_v2(text_with_markup):
    """Экранирует спецсимволы для MarkdownV2 (для системных сообщений бота)"""
    chars = r'_\*\[\]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(chars)}])', r'\\\1', str(text_with_markup))

def send_long_message(chat_id, text, reply_to_message=None, parse_mode="HTML"):
    """Send a message, splitting it if it's too long (Telegram limit: 4096 chars)."""

    # Конвертируем markdown в HTML если нужно
    if parse_mode == "HTML":
        text = markdown_to_html(text)

    if len(text) <= MAX_MESSAGE_LENGTH:
        if reply_to_message:
            bot.reply_to(reply_to_message, text, parse_mode=parse_mode)
        else:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
    else:
        # Split into chunks
        chunks = []
        current_chunk = ""
        for line in text.split('\n'):
            # If adding this line would exceed limit, save current chunk
            if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                if current_chunk:
                    current_chunk += '\n' + line
                else:
                    current_chunk = line
        if current_chunk:
            chunks.append(current_chunk)

        # Send each chunk
        for i, chunk in enumerate(chunks):
            if reply_to_message and i == 0:
                bot.reply_to(reply_to_message, chunk, parse_mode=parse_mode)
            else:
                bot.send_message(chat_id, chunk, parse_mode=parse_mode)


logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

# Настройка логирования (только в stdout для Docker)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
app_logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)

client = openai.Client(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)

# Initialize MCP Manager (global instance)
mcp_manager = None
if os.environ.get("MCP_ENABLED", "false").lower() == "true":
    try:
        from mcp_manager import MCPServerManager, load_mcp_configs_from_env

        configs = load_mcp_configs_from_env()
        mcp_manager = MCPServerManager(configs)
        app_logger.info(f"MCP Manager initialized with {len(configs)} server configs")
    except Exception as e:
        app_logger.error(f"Failed to initialize MCP Manager: {e}")
        mcp_manager = None


def get_s3_client():
    session = boto3.session.Session(
        aws_access_key_id=S3_KEY_ID, aws_secret_access_key=S3_KEY_SECRET
    )
    # Используй переменную окружения MINIO_ENDPOINT для своего S3
    endpoint_url = os.environ.get("MINIO_ENDPOINT", "https://storage.yandexcloud.net")
    return session.client(
        service_name="s3", endpoint_url=endpoint_url
    )


# Thread-safe typing state management
typing_states = {}  # {chat_id: threading.Event()}

# Rate limiting (requests per minute)
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60  # seconds
rate_limit_data = {}  # {chat_id: [timestamp1, timestamp2, ...]}

# Chat history limits
MAX_HISTORY_LENGTH = 50  # Maximum number of messages to keep in history

# Message and token limits
MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, use safe margin
MAX_VISION_TOKENS = 4000  # Max tokens for vision model responses

# MCP configuration
MCP_TOOL_TIMEOUT_SECONDS = 30  # Timeout for tool execution
MCP_MAX_ITERATIONS = 5  # Maximum tool call iterations to prevent loops

# Typing indicator
TYPING_INTERVAL_SECONDS = 4  # Interval for sending typing action

# Global event loop for async operations
_async_loop = None
_loop_thread = None


def get_or_create_event_loop():
    """Get or create a global event loop for async operations (thread-safe)"""
    global _async_loop, _loop_thread

    if _async_loop is None or not _async_loop.is_running():
        import threading

        def run_loop(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _async_loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=run_loop, args=(_async_loop,), daemon=True)
        _loop_thread.start()
        app_logger.info("Created global event loop for async operations")

    return _async_loop


def run_async(coro):
    """Run async coroutine in global event loop from sync context"""
    loop = get_or_create_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

# ============ Управление пользователями ============

def validate_username(username: str) -> bool:
    """
    Проверка валидности Telegram username.

    Требования:
    - Не пустой
    - Длина от 5 до 32 символов (Telegram ограничение)
    - Только латинские буквы, цифры и подчеркивание
    - Не может начинаться с цифры
    """
    if not username:
        return False

    if len(username) < 5 or len(username) > 32:
        return False

    # Regex: начинается с буквы или подчеркивания, далее буквы/цифры/подчеркивания
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', username):
        return False

    return True


def get_users_db():
    """Получить базу пользователей из S3"""
    s3client = get_s3_client()
    try:
        response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{ADMIN_CHAT_ID}_users.json"
        )
        return json.loads(response["Body"].read())
    except:
        return {"users": {}}


def save_users_db(users_db):
    """Сохранить базу пользователей в S3"""
    s3client = get_s3_client()
    try:
        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{ADMIN_CHAT_ID}_users.json",
            Body=json.dumps(users_db, indent=2),
        )
    except Exception as e:
        app_logger.error(f"Error saving users db: {e}")


def register_user(username, chat_id):
    """Зарегистрировать нового пользователя со статусом pending"""
    if not validate_username(username):
        app_logger.warning(f"Invalid username format: {username}")
        return "invalid_username"

    username_lower = username.lower()
    users_db = get_users_db()

    # Если пользователь уже есть, возвращаем его статус
    if username_lower in users_db["users"]:
        return users_db["users"][username_lower]["status"]

    # Создаем нового пользователя
    users_db["users"][username_lower] = {
        "chat_id": chat_id,
        "status": "pending",
        "first_seen": datetime.now().isoformat(),
        "username": username,
    }
    save_users_db(users_db)

    app_logger.info(f"New user registered: {username}, chat_id={chat_id}")

    # Уведомляем админа
    try:
        bot.send_message(
            ADMIN_CHAT_ID,
            f"🔔 *Новый пользователь*\n\n"
            f"👤 Username: `@{username}`\n"
            f"💬 Chat ID: `{chat_id}`\n"
            f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Для одобрения: `/approve {escape_markdown_v2(username)}`\n"
            f"Для отказа: `/deny {escape_markdown_v2(username)}`",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        app_logger.error(f"Error notifying admin: {e}")

    return "pending"


def get_user_status(username):
    """Получить статус пользователя"""
    if not username:
        return "denied"

    username_lower = username.lower()

    # Админ всегда имеет доступ
    if username_lower == ADMIN_USERNAME.lower():
        return "approved"

    users_db = get_users_db()
    user = users_db["users"].get(username_lower)
    return user["status"] if user else None


def set_user_status(username, status):
    """Установить статус пользователя"""
    if not username:
        return False

    username_lower = username.lower()
    users_db = get_users_db()

    if username_lower not in users_db["users"]:
        return False

    users_db["users"][username_lower]["status"] = status
    save_users_db(users_db)
    app_logger.info(f"User {username} status changed to: {status}")
    return True


def is_authorized(message):
    """Проверка доступа к боту"""
    username = message.from_user.username

    # Админ всегда имеет доступ
    if username and username.lower() == ADMIN_USERNAME.lower():
        return True

    # Регистрируем/проверяем пользователя
    status = register_user(username, message.chat.id)

    # Проверка на invalid_username
    if status == "invalid_username":
        return False

    return status == "approved"


def is_admin(message):
    """Проверка - является ли пользователь админом"""
    username = message.from_user.username
    return username and username.lower() == ADMIN_USERNAME.lower()


def check_rate_limit(chat_id):
    """
    Проверка rate limit для пользователя.
    Возвращает True если можно обрабатывать запрос, False если превышен лимит.
    """
    current_time = time.time()

    # Получаем или создаем список запросов для пользователя
    if chat_id not in rate_limit_data:
        rate_limit_data[chat_id] = []

    # Удаляем старые записи (старше RATE_LIMIT_WINDOW секунд)
    rate_limit_data[chat_id] = [
        timestamp for timestamp in rate_limit_data[chat_id]
        if current_time - timestamp < RATE_LIMIT_WINDOW
    ]

    # Проверяем лимит
    if len(rate_limit_data[chat_id]) >= RATE_LIMIT_REQUESTS:
        oldest_request = rate_limit_data[chat_id][0]
        wait_time = int(RATE_LIMIT_WINDOW - (current_time - oldest_request))
        app_logger.warning(
            f"Rate limit exceeded: chat_id={chat_id}, "
            f"requests={len(rate_limit_data[chat_id])}, "
            f"wait_time={wait_time}s"
        )
        return False, wait_time

    # Добавляем текущий запрос
    rate_limit_data[chat_id].append(current_time)
    return True, 0

def start_typing(chat_id):
    """Start typing indicator for a specific chat (thread-safe)"""
    if chat_id in typing_states:
        # Already typing for this chat
        return

    stop_event = threading.Event()
    typing_states[chat_id] = stop_event
    typing_thread = threading.Thread(target=typing, args=(chat_id, stop_event), daemon=True)
    typing_thread.start()

def typing(chat_id, stop_event):
    """Send typing action until stop_event is set"""
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception as e:
            app_logger.error(f"Error sending typing action for chat {chat_id}: {e}")
            break
        stop_event.wait(timeout=TYPING_INTERVAL_SECONDS)

def stop_typing(chat_id):
    """Stop typing indicator for a specific chat"""
    if chat_id in typing_states:
        typing_states[chat_id].set()
        del typing_states[chat_id]


def fetch_models():
    """Получить список моделей из API и сгруппировать по производителю"""
    try:
        models_url = f"{OPENAI_BASE_URL.rstrip('/')}/models"
        headers = {}
        if OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

        response = requests.get(
            models_url,
            headers=headers,
            timeout=5
        )
        response.raise_for_status()
        data = response.json()

        # Группируем модели по owned_by
        models_by_owner = defaultdict(list)
        for model in data.get("data", []):
            owner = model.get("owned_by", "unknown")
            model_id = model.get("id", "")
            if model_id:
                models_by_owner[owner].append(model_id)

        return dict(models_by_owner)
    except Exception as e:
        print(f"Error fetching models: {e}")
        # Возврат к дефолтному списку при ошибке
        return {
            "z.ai": ["glm-4.7"],
            "qwen": ["qwen3-coder-plus"],
            "openai": ["gpt-5.2"],
        }


@bot.message_handler(commands=["help", "start"])
def send_welcome(message):
    username = message.from_user.username

    # Проверяем авторизацию
    if not is_authorized(message):
        status = get_user_status(username)

        # Проверка на невалидный username
        if not username or not validate_username(username):
            bot.reply_to(
                message,
                "❌ *Неверный формат username*\\.\n\n"
                "Требования\\:\n"
                "• Длина 5\\-32 символа\n"
                "• Только латинские буквы, цифры и подчеркивание\n"
                "• Должен начинаться с буквы или подчеркивания\n\n"
                "Пожалуйста, установите корректный username в настройках Telegram\\.",
                parse_mode="MarkdownV2"
            )
            return

        if status == "pending":
            bot.reply_to(
                message,
                "⏳ *Ожидание подтверждения*\n\n"
                "Ваша заявка на использование бота отправлена администратору. "
                "Ожидайте ответа.",
                parse_mode="MarkdownV2",
            )
            return
        elif status == "denied":
            bot.reply_to(
                message,
                "❌ *Доступ запрещен*\n\n"
                "Администратор отклонил вашу заявку на использование бота.",
                parse_mode="MarkdownV2",
            )
            return
        else:
            bot.reply_to(
                message,
                "❌ У вас нет доступа к этому боту\\.\n\n"
                "Убедитесь что у вас установлен username в Telegram\\.",
                parse_mode="MarkdownV2"
            )
            return

    app_logger.info(f"Command /start or /help: user={username}, chat_id={message.chat.id}")

    # Для админа показываем расширенную справку
    if is_admin(message):
        help_text = (
            "*🤖 AI Bot \\- Панель администратора*\n\n"
            "👤 *Управление пользователями\\:*\n"
            "`/users` \\- список всех пользователей\n"
            "`/approve <username>` \\- разрешить доступ\n"
            "`/deny <username>` \\- запретить доступ\n\n"
            "⚙️ *Другие команды\\:*\n"
            "`/models` \\- список AI моделей\n"
            "`/model <name>` \\- выбрать модель\n"
            "`/new` \\- очистить историю чата\n"
            "`/image <prompt>` \\- генерация изображения\n\n"
            "🔧 *MCP Tools\\:*\n"
            "`/tools` \\- список доступных инструментов\n"
            "`/mcp on/off` \\- включить/выключить инструменты\n"
            "`/mcpstatus` \\- статус MCP серверов"
        )
    else:
        help_text = (
            "*🤖 Привет\\! Я AI бот\\. Спроси меня что\\-нибудь\\!*\n\n"
            "⚙️ *Доступные команды\\:*\n"
            "`/models` \\- список AI моделей\n"
            "`/model <name>` \\- выбрать модель\n"
            "`/new` \\- очистить истории чата\n"
            "`/image <prompt>` \\- генерация изображения\n\n"
            "🔧 *MCP Tools\\:*\n"
            "`/tools` \\- список доступных инструментов\n"
            "`/mcp on/off` \\- включить/выключить инструменты"
        )

    bot.reply_to(message, help_text, parse_mode="MarkdownV2")


@bot.message_handler(commands=["users"])
def list_users(message):
    """Список всех пользователей (только для админа)"""
    if not is_admin(message):
        bot.reply_to(message, "❌ Эта команда доступна только администратору\\.", parse_mode="MarkdownV2")
        return

    users_db = get_users_db()
    users = users_db.get("users", {})

    if not users:
        bot.reply_to(message, "👥 Пользователей пока нет\\.", parse_mode="MarkdownV2")
        return

    # Группируем по статусам
    status_emoji = {
        "approved": "✅",
        "pending": "⏳",
        "denied": "❌",
    }

    text = "👥 *Список пользователей:*\n\n"

    for status in ["pending", "approved", "denied"]:
        status_users = [u for u in users.values() if u["status"] == status]
        if status_users:
            text += f"{status_emoji[status]} *{status.title()}* \\({len(status_users)}\\):\n"
            for user in status_users:
                username = user.get("username", "unknown")
                chat_id = user.get("chat_id", "unknown")
                first_seen = user.get("first_seen", "unknown")[:10]
                text += f"  • `@{escape_markdown_v2(username)}` — `{escape_markdown_v2(str(chat_id))}` — {escape_markdown_v2(first_seen)}\n"
            text += "\n"

    bot.reply_to(message, text, parse_mode="MarkdownV2")
    app_logger.info(f"Command /users: admin={message.from_user.username}, total_users={len(users)}")


def update_user_access(message, username_arg: str, new_status: str, command_name: str):
    """
    Общая функция для одобрения/отклонения пользователя.

    Args:
        message: Telegram message object
        username_arg: аргумент команды (может содержать @)
        new_status: "approved" или "denied"
        command_name: название команды для сообщений об ошибках
    """
    username = username_arg.strip().lstrip("@")

    if not username:
        bot.reply_to(message, "❌ Некорректное имя пользователя", parse_mode="MarkdownV2")
        return

    # Сообщения для разных статусов
    status_messages = {
        "approved": {
            "user": "✅ *Доступ разрешён\\!*\n\nАдминистратор одобрил вашу заявку\\. Теперь вы можете использовать бота\\.",
            "admin": f"✅ Пользователь `@{escape_markdown_v2(username)}` одобрен\\.",
            "log": "approved"
        },
        "denied": {
            "user": "❌ *Доступ запрещён\\!*\n\nАдминистратор отклонил вашу заявку\\.",
            "admin": f"❌ Пользователю `@{escape_markdown_v2(username)}` запрещён доступ\\.",
            "log": "denied"
        }
    }

    messages = status_messages.get(new_status)
    if not messages:
        app_logger.error(f"Invalid status: {new_status}")
        return

    # Обновляем статус пользователя
    if set_user_status(username, new_status):
        # Уведомляем пользователя
        users_db = get_users_db()
        user = users_db["users"].get(username.lower())
        if user:
            chat_id = user.get("chat_id")
            try:
                bot.send_message(chat_id, messages["user"], parse_mode="MarkdownV2")
            except Exception as e:
                app_logger.warning(f"Failed to notify user {username}: {e}")

        # Уведомляем админа
        bot.reply_to(message, messages["admin"], parse_mode="MarkdownV2")
        app_logger.info(f"User {messages['log']}: {username} by admin {message.from_user.username}")
    else:
        # Пользователь не найден
        bot.reply_to(
            message,
            f"❌ Пользователь `@{escape_markdown_v2(username)}` не найден\\.",
            parse_mode="MarkdownV2",
        )


@bot.message_handler(commands=["approve"])
def approve_user(message):
    """Одобрить пользователя (только для админа)"""
    if not is_admin(message):
        return

    args = message.text.split("/approve", 1)[1].strip()
    if not args:
        bot.reply_to(message, "Используйте\\: `/approve <username>`", parse_mode="MarkdownV2")
        return

    update_user_access(message, args, "approved", "approve")


@bot.message_handler(commands=["deny"])
def deny_user(message):
    """Запретить пользователя (только для админа)"""
    if not is_admin(message):
        return

    args = message.text.split("/deny", 1)[1].strip()
    if not args:
        bot.reply_to(message, "Используйте\\: `/deny <username>`", parse_mode="MarkdownV2")
        return

    update_user_access(message, args, "denied", "deny")


@bot.message_handler(commands=["new"])
def clear_history(message):
    if not is_authorized(message):
        return
    clear_history_for_chat(message.chat.id)
    app_logger.info(f"History cleared: user={message.from_user.username}, chat_id={message.chat.id}")
    bot.reply_to(message, "История чата очищена!")


@bot.message_handler(commands=["models"])
def list_models(message):
    if not is_authorized(message):
        return

    current_model = get_user_model(message.chat.id)
    models_by_owner = fetch_models()

    models_list = "📋 *Доступные модели:*\n\n"

    for owner, models in sorted(models_by_owner.items()):
        models_list += f"🏢 *{owner}*\n"
        for model_id in sorted(models):
            prefix = "▶️ " if model_id == current_model else "  "
            models_list += f"{prefix}`{model_id}`\n"
        models_list += "\n"

    models_list += f"🔧 Текущая модель: `{current_model}`"
    models_list += "\n\nИспользуй /model <название> для смены модели"

    bot.reply_to(message, models_list, parse_mode="Markdown")
    app_logger.info(f"Command /models: user={message.from_user.username}, chat_id={message.chat.id}")


@bot.message_handler(commands=["model"])
def set_model(message):
    if not is_authorized(message):
        return
    args = message.text.split("/model")[1].strip()
    if len(args) == 0:
        bot.reply_to(
            message,
            "Используй: /model <название>\n\nСписок моделей: /models",
            parse_mode="Markdown",
        )
        return

    model_name = args.strip()

    # Проверяем, существует ли модель
    models_by_owner = fetch_models()
    all_models = []
    for models in models_by_owner.values():
        all_models.extend(models)

    if model_name not in all_models:
        bot.reply_to(
            message,
            f"❌ Модель `{model_name}` не найдена.\n\nСписок моделей: /models",
            parse_mode="Markdown",
        )
        return

    set_user_model(message.chat.id, model_name)
    bot.reply_to(
        message,
        f"✅ Модель изменена на: `{model_name}`",
        parse_mode="Markdown",
    )
    app_logger.info(f"Model changed: user={message.from_user.username}, chat_id={message.chat.id}, model={model_name}")


@bot.message_handler(commands=["tools"])
def list_tools(message):
    if not is_authorized(message):
        return

    if not mcp_manager:
        bot.reply_to(message, "🔧 MCP tools are not enabled\\.", parse_mode="MarkdownV2")
        return

    try:
        tools = run_async(mcp_manager.get_all_tools())

        if not tools:
            bot.reply_to(message, "🔧 No MCP tools available\\.", parse_mode="MarkdownV2")
            return

        # Format tool list grouped by server
        tools_text = "🔧 *Available MCP Tools:*\n\n"

        tools_by_server = {}
        for tool in tools:
            server_name = tool.get("_mcp_server", "unknown")
            if server_name not in tools_by_server:
                tools_by_server[server_name] = []
            tools_by_server[server_name].append(tool["function"])

        for server, server_tools in sorted(tools_by_server.items()):
            tools_text += f"📦 *{escape_markdown_v2(server)}* \\({len(server_tools)} tools\\)\n"
            for tool_func in server_tools:
                name = tool_func["name"]
                # Just show tool name, no description (to keep message short)
                tools_text += f"  \\- `{escape_markdown_v2(name)}`\n"
            tools_text += "\n"

        mcp_status = "✅ enabled" if should_use_mcp_for_user(message.chat.id) else "❌ disabled"
        tools_text += f"💡 MCP tools for you\\: {mcp_status}\n"
        tools_text += "Use `/mcp on` or `/mcp off` to toggle\\.\n"
        tools_text += f"\nTotal\\: {len(tools)} tools available\\."

        # Check if message is too long (Telegram limit is 4096 chars)
        if len(tools_text) > 4000:
            # Split into multiple messages
            messages = []
            current_msg = "🔧 *Available MCP Tools:*\n\n"

            for server, server_tools in sorted(tools_by_server.items()):
                server_section = f"📦 *{escape_markdown_v2(server)}* \\({len(server_tools)} tools\\)\n"
                for tool_func in server_tools:
                    server_section += f"  \\- `{escape_markdown_v2(tool_func['name'])}`\n"
                server_section += "\n"

                if len(current_msg) + len(server_section) > 3500:
                    messages.append(current_msg)
                    current_msg = ""

                current_msg += server_section

            if current_msg:
                current_msg += f"\n💡 MCP tools\\: {mcp_status}\n"
                current_msg += f"Total\\: {len(tools)} tools"
                messages.append(current_msg)

            # Send multiple messages
            for msg in messages:
                bot.send_message(message.chat.id, msg, parse_mode="MarkdownV2")
        else:
            bot.reply_to(message, tools_text, parse_mode="MarkdownV2")
        app_logger.info(f"/tools: user={message.from_user.username}, count={len(tools)}")

    except Exception as e:
        app_logger.error(f"Error listing tools: {e}")
        bot.reply_to(message, f"❌ Error listing tools: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")


@bot.message_handler(commands=["mcp"])
def toggle_mcp(message):
    if not is_authorized(message):
        return

    if not mcp_manager:
        bot.reply_to(message, "🔧 MCP tools are not available\\.", parse_mode="MarkdownV2")
        return

    args = message.text.split("/mcp")[1].strip().lower()

    if args == "on":
        set_mcp_for_user(message.chat.id, True)
        bot.reply_to(message, "✅ MCP tools enabled\\.", parse_mode="MarkdownV2")
        app_logger.info(f"MCP enabled: user={message.from_user.username}")
    elif args == "off":
        set_mcp_for_user(message.chat.id, False)
        bot.reply_to(message, "❌ MCP tools disabled\\.", parse_mode="MarkdownV2")
        app_logger.info(f"MCP disabled: user={message.from_user.username}")
    else:
        current_status = "enabled" if should_use_mcp_for_user(message.chat.id) else "disabled"
        bot.reply_to(
            message,
            f"🔧 *MCP Tools\\:* {escape_markdown_v2(current_status)}\n\n"
            f"`/mcp on` \\- enable tools\n"
            f"`/mcp off` \\- disable tools\n"
            f"`/tools` \\- list available tools",
            parse_mode="MarkdownV2"
        )


@bot.message_handler(commands=["mcpstatus"])
def mcp_status(message):
    if not is_admin(message):
        bot.reply_to(message, "❌ Admin only\\.", parse_mode="MarkdownV2")
        return

    if not mcp_manager:
        bot.reply_to(message, "🔧 MCP Manager not initialized\\.", parse_mode="MarkdownV2")
        return

    try:
        status = mcp_manager.get_server_status()

        status_text = "🔧 *MCP Server Status:*\n\n"
        for server_name, server_status in status.items():
            emoji = "✅" if server_status == "connected" else "❌"
            status_text += f"{emoji} *{escape_markdown_v2(server_name)}*: `{escape_markdown_v2(server_status)}`\n"

        bot.reply_to(message, status_text, parse_mode="MarkdownV2")
        app_logger.info(f"/mcpstatus: admin={message.from_user.username}")

    except Exception as e:
        app_logger.error(f"Error getting MCP status: {e}")
        bot.reply_to(message, f"❌ Error: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")


@bot.message_handler(commands=["image"])
def image(message):
    if not is_authorized(message):
        return

    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit (image): user={message.from_user.username}, chat_id={message.chat.id}")
            return

    prompt = message.text.split("/image")[1].strip()
    if len(prompt) == 0:
        bot.reply_to(message, "Введите запрос после команды /image")
        return

    app_logger.info(f"Image generation request: user={message.from_user.username}, chat_id={message.chat.id}, prompt='{prompt[:100]}...'")

    try:
        response = client.images.generate(
            prompt=prompt, n=1, size="1024x1024", model="dall-e-3"
        )
        image_url = response.data[0].url
        app_logger.info(f"Image generated: user={message.from_user.username}, chat_id={message.chat.id}, url={image_url}")
    except Exception as e:
        app_logger.error(f"Image generation failed: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, "Произошла ошибка, попробуйте позже!")
        return

    bot.send_photo(
        message.chat.id,
        image_url,
        reply_to_message_id=message.message_id,
    )


@bot.message_handler(func=lambda message: is_authorized(message), content_types=["text", "photo"])
def echo_message(message):
    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit: user={message.from_user.username}, chat_id={message.chat.id}")
            return

    start_typing(message.chat.id)

    try:
        text = message.text
        image_content = None
        has_photo = False

        photo = message.photo
        if photo is not None:
            has_photo = True
            photo = photo[0]
            file_info = bot.get_file(photo.file_id)
            image_content = bot.download_file(file_info.file_path)
            text = message.caption
            if text is None or len(text) == 0:
                text = "Что на картинке?"

        ai_response = process_text_message(text, message.chat.id, image_content)

        log_msg_type = "photo" if has_photo else "text"
        app_logger.info(
            f"Message processed: user={message.from_user.username}, chat_id={message.chat.id}, "
            f"type={log_msg_type}, prompt_length={len(text) if text else 0}, "
            f"response_length={len(ai_response) if ai_response else 0}"
        )
    except Exception as e:
        app_logger.error(f"Error processing message: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    stop_typing(message.chat.id)
    # Send with automatic splitting for long messages
    # Falls back to plain text on parse error
    try:
        send_long_message(message.chat.id, ai_response, reply_to_message=message, parse_mode="HTML")
    except Exception as e:
        if "can't parse entities" in str(e) or "Bad Request" in str(e):
            app_logger.warning(f"HTML parse error, sending as plain text: {e}")
            # Отправляем как обычный текст без форматирования
            if len(ai_response) <= MAX_MESSAGE_LENGTH:
                bot.reply_to(message, ai_response)
            else:
                # Split into chunks for plain text
                chunks = []
                current_chunk = ""
                for line in ai_response.split('\n'):
                    if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line
                    else:
                        if current_chunk:
                            current_chunk += '\n' + line
                        else:
                            current_chunk = line
                if current_chunk:
                    chunks.append(current_chunk)

                for i, chunk in enumerate(chunks):
                    if i == 0:
                        bot.reply_to(message, chunk)
                    else:
                        bot.send_message(message.chat.id, chunk)
        else:
            raise


@bot.message_handler(
    func=lambda msg: is_authorized(msg) and msg.voice.mime_type == "audio/ogg", content_types=["voice"]
)
def voice(message):
    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit (voice): user={message.from_user.username}, chat_id={message.chat.id}")
            return

    app_logger.info(f"Voice message received: user={message.from_user.username}, chat_id={message.chat.id}")

    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    # Create unique temporary file to avoid race conditions
    temp_file = None
    try:
        response = client.audio.transcriptions.create(
            file=("file.ogg", downloaded_file, "audio/ogg"),
            model="whisper-1",
        )
        transcribed_text = response.text
        app_logger.info(f"Voice transcribed: user={message.from_user.username}, chat_id={message.chat.id}, text='{transcribed_text[:100]}...'")

        ai_response = process_text_message(transcribed_text, message.chat.id)
        ai_voice_response = client.audio.speech.create(
            input=ai_response,
            voice="nova",
            model="tts-1-hd",
            response_format="opus",
        )

        # Use unique filename to avoid race conditions between different users
        temp_file = os.path.join(tempfile.gettempdir(), f"ai_voice_{message.chat.id}_{uuid.uuid4().hex}.ogg")
        with open(temp_file, "wb") as f:
            f.write(ai_voice_response.content)

        with open(temp_file, "rb") as f:
            bot.send_voice(
                message.chat.id,
                voice=InputFile(f),
                reply_to_message_id=message.message_id,
            )
    except Exception as e:
        app_logger.error(f"Voice processing failed: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                app_logger.warning(f"Failed to remove temp file {temp_file}: {e}")


def get_user_model(chat_id) -> str:
    """Получить выбранную модель пользователя или дефолтную"""
    s3client = get_s3_client()
    try:
        response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}_settings.json"
        )
        settings = json.loads(response["Body"].read())
        return settings.get("model", "glm-4.7")
    except:
        return "glm-4.7"


def set_user_model(chat_id, model: str):
    """Сохранить выбранную модель пользователя"""
    s3client = get_s3_client()
    try:
        # Читаем текущие настройки
        try:
            response = s3client.get_object(
                Bucket=S3_BUCKET, Key=f"{chat_id}_settings.json"
            )
            settings = json.loads(response["Body"].read())
        except:
            settings = {}

        settings["model"] = model

        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}_settings.json",
            Body=json.dumps(settings),
        )
    except Exception as e:
        print(f"Error saving user model: {e}")


def should_use_mcp_for_user(chat_id) -> bool:
    """Check if MCP tools are enabled for this user"""
    s3client = get_s3_client()
    try:
        response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}_settings.json"
        )
        settings = json.loads(response["Body"].read())
        return settings.get("mcp_enabled", True)  # Default: enabled
    except:
        return True


def set_mcp_for_user(chat_id, enabled: bool):
    """Enable/disable MCP tools for a user"""
    s3client = get_s3_client()
    try:
        try:
            response = s3client.get_object(
                Bucket=S3_BUCKET, Key=f"{chat_id}_settings.json"
            )
            settings = json.loads(response["Body"].read())
        except:
            settings = {}

        settings["mcp_enabled"] = enabled

        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}_settings.json",
            Body=json.dumps(settings),
        )
    except Exception as e:
        app_logger.error(f"Error saving MCP setting: {e}")


def process_text_message(text, chat_id, image_content=None) -> str:
    # Если есть изображение, используем vision модель
    if image_content is not None:
        model = "gpt-4-vision-preview"
    else:
        model = get_user_model(chat_id)

    app_logger.info(f"Processing message: chat_id={chat_id}, model={model}, has_image={image_content is not None}, text='{text[:200]}...'")

    max_tokens = None

    # read current chat history
    s3client = get_s3_client()
    history = []
    try:
        history_object_response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}.json"
        )
        history = json.loads(history_object_response["Body"].read())
    except:
        pass

    # Limit history length to prevent memory overflow and reduce API costs
    if len(history) > MAX_HISTORY_LENGTH:
        old_length = len(history)
        # Keep only the last MAX_HISTORY_LENGTH messages
        history = history[-MAX_HISTORY_LENGTH:]
        app_logger.info(
            f"History trimmed: chat_id={chat_id}, "
            f"old_length={old_length}, new_length={len(history)}"
        )

    history_text_only = history.copy()
    history_text_only.append({"role": "user", "content": text})

    # Add system message to keep responses concise (avoid Telegram 4096 char limit)
    system_message = {
        "role": "system",
        "content": "Keep your responses concise and to the point. Prefer shorter answers over long explanations. If listing items, limit to the most important ones. Maximum response length: ~3000 characters."
    }
    history = [system_message] + history

    if image_content is not None:
        model = "gpt-4-vision-preview"
        max_tokens = MAX_VISION_TOKENS
        base64_image_content = base64.b64encode(image_content).decode("utf-8")
        base64_image_content = f"data:image/jpeg;base64,{base64_image_content}"
        history.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": base64_image_content}},
                ],
            }
        )
    else:
        history.append({"role": "user", "content": text})

    # Get MCP tools if enabled
    tools_param = None
    if mcp_manager and should_use_mcp_for_user(chat_id):
        try:
            tools_param = run_async(mcp_manager.get_all_tools())
            app_logger.info(f"MCP tools available: {len(tools_param)} tools")
        except Exception as e:
            app_logger.error(f"MCP failed, continuing without tools: {e}")
            tools_param = None  # Graceful degradation

    try:
        chat_completion = client.chat.completions.create(
            model=model,
            messages=history,
            max_tokens=max_tokens,
            tools=tools_param,
            tool_choice="auto" if tools_param else None
        )
    except Exception as e:
        app_logger.error(f"API error: chat_id={chat_id}, model={model}, error={str(e)}")
        if type(e).__name__ == "BadRequestError":
            clear_history_for_chat(chat_id)
            return process_text_message(text, chat_id)
        else:
            raise e

    # Tool calling loop
    message = chat_completion.choices[0].message

    if message.tool_calls:
        iteration = 0

        while message.tool_calls and iteration < MCP_MAX_ITERATIONS:
            iteration += 1
            app_logger.info(f"Tool calls (iteration {iteration}): {[tc.function.name for tc in message.tool_calls]}")

            # Add assistant message with tool calls to history
            history.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            })

            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                try:
                    result = run_async(
                        mcp_manager.execute_tool(tool_name, tool_args)
                    )

                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(result) if not isinstance(result, str) else result
                    })

                    app_logger.info(f"Tool executed: {tool_name}, result_length={len(str(result))}")

                except Exception as e:
                    error_msg = f"Error executing tool {tool_name}: {str(e)}"
                    app_logger.error(error_msg)

                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps({"error": error_msg})
                    })

            # Retry API call with tool results
            try:
                chat_completion = client.chat.completions.create(
                    model=model,
                    messages=history,
                    max_tokens=max_tokens,
                    tools=tools_param,
                    tool_choice="auto" if tools_param else None
                )
                message = chat_completion.choices[0].message
            except Exception as e:
                app_logger.error(f"API error during tool call iteration: {e}")
                break

        if iteration >= MCP_MAX_ITERATIONS:
            app_logger.warning(f"Max tool call iterations ({MCP_MAX_ITERATIONS}) reached for chat_id={chat_id}")

    # Extract final response
    ai_response = message.content if message.content else "I used tools but couldn't generate a text response."

    history_text_only.append({"role": "assistant", "content": ai_response})

    app_logger.info(
        f"AI response: chat_id={chat_id}, model={model}, "
        f"response_length={len(ai_response)}, response_preview='{ai_response[:200]}...'"
    )

    # save current chat history
    s3client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{chat_id}.json",
        Body=json.dumps(history_text_only),
    )

    return ai_response


def clear_history_for_chat(chat_id):
    try:
        s3client = get_s3_client()
        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}.json",
            Body=json.dumps([]),
        )
    except:
        pass


# AWS Lambda handler для webhook-режима (опционально)
def handler(event, context):
    message = json.loads(event["body"])
    update = telebot.types.Update.de_json(message)

    if (
        update.message is not None
        and update.message.from_user.username.lower() in TG_BOT_CHATS
    ):
        try:
            bot.process_new_updates([update])
        except Exception as e:
            print(e)

    return {
        "statusCode": 200,
        "body": "ok",
    }


# Запуск бота в режиме polling
if __name__ == "__main__":
    print("Бот запущен в режиме polling...")
    bot.infinity_polling()
