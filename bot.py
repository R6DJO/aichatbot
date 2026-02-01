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
from datetime import datetime
from telebot.types import InputFile
from dotenv import load_dotenv
from collections import defaultdict

# Загрузка переменных окружения из .env
load_dotenv()

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "R6DJO")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "1212054"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1")
S3_KEY_ID = os.environ.get("S3_KEY_ID")
S3_KEY_SECRET = os.environ.get("S3_KEY_SECRET")
S3_BUCKET = os.environ.get("S3_BUCKET")


logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

# Настройка логирования запросов
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
app_logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)

client = openai.Client(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)


def get_s3_client():
    session = boto3.session.Session(
        aws_access_key_id=S3_KEY_ID, aws_secret_access_key=S3_KEY_SECRET
    )
    # Используй переменную окружения MINIO_ENDPOINT для своего S3
    endpoint_url = os.environ.get("MINIO_ENDPOINT", "https://storage.yandexcloud.net")
    return session.client(
        service_name="s3", endpoint_url=endpoint_url
    )


is_typing = False

# ============ Управление пользователями ============

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
    if not username:
        return None

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
            f"Для одобрения: `/approve {username}`\n"
            f"Для отказа: `/deny {username}`",
            parse_mode="Markdown",
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

    return status == "approved"


def is_admin(message):
    """Проверка - является ли пользователь админом"""
    username = message.from_user.username
    return username and username.lower() == ADMIN_USERNAME.lower()

def start_typing(chat_id):
    global is_typing
    is_typing = True
    typing_thread = threading.Thread(target=typing, args=(chat_id,))
    typing_thread.start()

def typing(chat_id):
    global is_typing
    while is_typing:
        bot.send_chat_action(chat_id, "typing")
        time.sleep(4)

def stop_typing():
    global is_typing
    is_typing = False


def fetch_models():
    """Получить список моделей из API и сгруппировать по производителю"""
    try:
        models_url = f"{OPENAI_BASE_URL.rstrip('/')}/models"
        response = requests.get(models_url, timeout=5)
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
        if status == "pending":
            bot.reply_to(
                message,
                "⏳ *Ожидание подтверждения*\n\n"
                "Ваша заявка на использование бота отправлена администратору. "
                "Ожидайте ответа.",
                parse_mode="Markdown",
            )
            return
        elif status == "denied":
            bot.reply_to(
                message,
                "❌ *Доступ запрещен*\n\n"
                "Администратор отклонил вашу заявку на использование бота.",
                parse_mode="Markdown",
            )
            return
        else:
            bot.reply_to(message, "❌ У вас нет доступа к этому боту.\n\nУбедитесь что у вас установлен username в Telegram.", parse_mode="Markdown")
            return

    app_logger.info(f"Command /start or /help: user={username}, chat_id={message.chat.id}")

    # Для админа показываем расширенную справку
    if is_admin(message):
        help_text = (
            "*🤖 AI Bot - Панель администратора*\n\n"
            "👤 *Управление пользователями:*\n"
            "`/users` — список всех пользователей\n"
            "`/approve <username>` — разрешить доступ\n"
            "`/deny <username>` — запретить доступ\n\n"
            "⚙️ *Другие команды:*\n"
            "`/models` — список AI моделей\n"
            "`/model <name>` — выбрать модель\n"
            "`/new` — очистить историю чата\n"
            "`/image <prompt>` — генерация изображения"
        )
    else:
        help_text = (
            "*🤖 Привет! Я AI бот. Спроси меня что-нибудь!*\n\n"
            "⚙️ *Доступные команды:*\n"
            "`/models` — список AI моделей\n"
            "`/model <name>` — выбрать модель\n"
            "`/new` — очистить историю чата\n"
            "`/image <prompt>` — генерация изображения"
        )

    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["users"])
def list_users(message):
    """Список всех пользователей (только для админа)"""
    if not is_admin(message):
        bot.reply_to(message, "❌ Эта команда доступна только администратору.", parse_mode="Markdown")
        return

    users_db = get_users_db()
    users = users_db.get("users", {})

    if not users:
        bot.reply_to(message, "👥 Пользователей пока нет.", parse_mode="Markdown")
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
            text += f"{status_emoji[status]} *{status.title()}* ({len(status_users)}):\n"
            for user in status_users:
                username = user.get("username", "unknown")
                chat_id = user.get("chat_id", "unknown")
                first_seen = user.get("first_seen", "unknown")[:10]
                text += f"  • `@{username}` — `{chat_id}` — {first_seen}\n"
            text += "\n"

    bot.reply_to(message, text, parse_mode="Markdown")
    app_logger.info(f"Command /users: admin={message.from_user.username}, total_users={len(users)}")


@bot.message_handler(commands=["approve"])
def approve_user(message):
    """Одобрить пользователя (только для админа)"""
    if not is_admin(message):
        return

    args = message.text.split("/approve")[1].strip()
    if len(args) == 0:
        bot.reply_to(message, "Используйте: `/approve <username>`", parse_mode="Markdown")
        return

    username = args.strip().lstrip("@")
    if not username:
        bot.reply_to(message, "❌ Некорректное имя пользователя", parse_mode="Markdown")
        return

    if set_user_status(username, "approved"):
        users_db = get_users_db()
        user = users_db["users"].get(username.lower())
        if user:
            chat_id = user.get("chat_id")
            try:
                bot.send_message(
                    chat_id,
                    f"✅ *Доступ разрешён!*\n\n"
                    f"Администратор одобрил вашу заявку. Теперь вы можете использовать бота.",
                    parse_mode="Markdown",
                )
            except:
                pass

        bot.reply_to(
            message,
            f"✅ Пользователь `@{username}` одобрен.",
            parse_mode="Markdown",
        )
        app_logger.info(f"User approved: {username} by admin {message.from_user.username}")
    else:
        bot.reply_to(
            message,
            f"❌ Пользователь `@{username}` не найден.",
            parse_mode="Markdown",
        )


@bot.message_handler(commands=["deny"])
def deny_user(message):
    """Запретить пользователя (только для админа)"""
    if not is_admin(message):
        return

    args = message.text.split("/deny")[1].strip()
    if len(args) == 0:
        bot.reply_to(message, "Используйте: `/deny <username>`", parse_mode="Markdown")
        return

    username = args.strip().lstrip("@")
    if not username:
        bot.reply_to(message, "❌ Некорректное имя пользователя", parse_mode="Markdown")
        return

    if set_user_status(username, "denied"):
        users_db = get_users_db()
        user = users_db["users"].get(username.lower())
        if user:
            chat_id = user.get("chat_id")
            try:
                bot.send_message(
                    chat_id,
                    f"❌ *Доступ запрещён*\n\n"
                    f"Администратор отклонил вашу заявку.",
                    parse_mode="Markdown",
                )
            except:
                pass

        bot.reply_to(
            message,
            f"❌ Пользователю `@{username}` запрещён доступ.",
            parse_mode="Markdown",
        )
        app_logger.info(f"User denied: {username} by admin {message.from_user.username}")
    else:
        bot.reply_to(
            message,
            f"❌ Пользователь `@{username}` не найден.",
            parse_mode="Markdown",
        )
    if not is_authorized(message):
        bot.reply_to(message, "У вас нет доступа к этому боту.")
        return
    bot.reply_to(
        message,
        ("Привет! Я AI бот. Спроси меня что-нибудь!"),
        parse_mode="Markdown",
    )


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


@bot.message_handler(commands=["image"])
def image(message):
    if not is_authorized(message):
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

    stop_typing()
    bot.reply_to(message, ai_response, parse_mode="Markdown")


@bot.message_handler(
    func=lambda msg: is_authorized(msg) and msg.voice.mime_type == "audio/ogg", content_types=["voice"]
)
def voice(message):
    app_logger.info(f"Voice message received: user={message.from_user.username}, chat_id={message.chat.id}")

    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

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
        with open("/tmp/ai_voice_response.ogg", "wb") as f:
            f.write(ai_voice_response.content)
    except Exception as e:
        app_logger.error(f"Voice processing failed: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    with open("/tmp/ai_voice_response.ogg", "rb") as f:
        bot.send_voice(
            message.chat.id,
            voice=InputFile(f),
            reply_to_message_id=message.message_id,
        )


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

    history_text_only = history.copy()
    history_text_only.append({"role": "user", "content": text})

    if image_content is not None:
        model = "gpt-4-vision-preview"
        max_tokens = 4000
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

    try:
        chat_completion = client.chat.completions.create(
            model=model, messages=history, max_tokens=max_tokens
        )
    except Exception as e:
        app_logger.error(f"API error: chat_id={chat_id}, model={model}, error={str(e)}")
        if type(e).__name__ == "BadRequestError":
            clear_history_for_chat(chat_id)
            return process_text_message(text, chat_id)
        else:
            raise e

    ai_response = chat_completion.choices[0].message.content
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
