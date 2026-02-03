"""
User command handlers.
"""

from core.telegram import bot, app_logger
from core.openai_client import client
from auth.access_control import is_authorized
from models.model_manager import fetch_models
from storage.user_settings import get_user_model, set_user_model
from storage.chat_history import clear_chat_history
from utils.decorators import require_auth, rate_limited, log_command, handle_errors
from config.help_texts import HELP_TEXTS


@bot.message_handler(commands=["help", "start"])
@require_auth()
def send_welcome(message):
    # Для админа показываем расширенную справку
    from auth.access_control import is_admin

    help_text = HELP_TEXTS["admin"] if is_admin(message) else HELP_TEXTS["user"]
    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["new"])
@require_auth()
@log_command
@handle_errors("❌ Не удалось очистить историю. Попробуйте позже.")
def clear_history(message):
    success = clear_chat_history(message.chat.id)
    if success:
        bot.reply_to(message, "✅ История чата очищена!")
    else:
        raise Exception("Failed to clear chat history")


@bot.message_handler(commands=["models"])
@require_auth()
@log_command
@handle_errors()
def list_models(message):
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
@require_auth()
@log_command
@handle_errors()
def set_model(message):
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


@bot.message_handler(commands=["image"])
@require_auth()
@rate_limited
@log_command
@handle_errors("Произошла ошибка, попробуйте позже!")
def image(message):
    prompt = message.text.split("/image")[1].strip()
    if len(prompt) == 0:
        bot.reply_to(message, "Введите запрос после команды /image")
        return

    response = client.images.generate(
        prompt=prompt, n=1, size="1024x1024", model="dall-e-3"
    )
    image_url = response.data[0].url

    bot.send_photo(
        message.chat.id,
        image_url,
        reply_to_message_id=message.message_id,
    )
