"""
User command handlers.
"""

from core.telegram import bot, app_logger
from core.openai_client import client
from auth.access_control import is_authorized, is_admin
from auth.validators import validate_username
from auth.user_manager import get_user_status
from models.model_manager import fetch_models
from storage.user_settings import get_user_model, set_user_model
from storage.chat_history import clear_chat_history
from utils.rate_limiter import check_rate_limit


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
                "❌ Неверный формат username.\n\n"
                "Требования:\n"
                "• Длина 5-32 символа\n"
                "• Только латинские буквы, цифры и подчеркивание\n"
                "• Должен начинаться с буквы или подчеркивания\n\n"
                "Пожалуйста, установите корректный username в настройках Telegram."
            )
            return

        if status == "pending":
            bot.reply_to(
                message,
                "⏳ Ожидание подтверждения\n\n"
                "Ваша заявка на использование бота отправлена администратору. "
                "Ожидайте ответа."
            )
            return
        elif status == "denied":
            bot.reply_to(
                message,
                "❌ Доступ запрещен\n\n"
                "Администратор отклонил вашу заявку на использование бота."
            )
            return
        else:
            bot.reply_to(
                message,
                "❌ У вас нет доступа к этому боту.\n\n"
                "Убедитесь что у вас установлен username в Telegram."
            )
            return

    app_logger.info(f"Command /start or /help: user={username}, chat_id={message.chat.id}")

    # Для админа показываем расширенную справку
    if is_admin(message):
        help_text = (
            "*🤖 AI Bot - Панель администратора*\n\n"
            "👤 *Управление пользователями:*\n"
            "`/users` - список всех пользователей\n"
            "`/approve <username>` - разрешить доступ\n"
            "`/deny <username>` - запретить доступ\n\n"
            "⚙️ *Другие команды:*\n"
            "`/models` - список AI моделей\n"
            "`/model <name>` - выбрать модель\n"
            "`/new` - очистить историю чата\n"
            "`/image <prompt>` - генерация изображения\n\n"
            "🔧 *MCP Tools:*\n"
            "`/tools` - список доступных инструментов\n"
            "`/mcp on/off` - включить/выключить инструменты\n"
            "`/mcpstatus` - статус MCP серверов"
        )
    else:
        help_text = (
            "*🤖 Привет! Я AI бот. Спроси меня что-нибудь!*\n\n"
            "⚙️ *Доступные команды:*\n"
            "`/models` - список AI моделей\n"
            "`/model <name>` - выбрать модель\n"
            "`/new` - очистить истории чата\n"
            "`/image <prompt>` - генерация изображения\n\n"
            "🔧 *MCP Tools:*\n"
            "`/tools` - список доступных инструментов\n"
            "`/mcp on/off` - включить/выключить инструменты"
        )

    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["new"])
def clear_history(message):
    if not is_authorized(message):
        return
    success = clear_chat_history(message.chat.id)
    if success:
        app_logger.info(f"History cleared: user={message.from_user.username}, chat_id={message.chat.id}")
        bot.reply_to(message, "✅ История чата очищена!")
    else:
        app_logger.error(f"Failed to clear history: user={message.from_user.username}, chat_id={message.chat.id}")
        bot.reply_to(message, "❌ Не удалось очистить историю. Попробуйте позже.")


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
