"""
User command handlers.
"""

from core.telegram import bot, app_logger
from core.openai_client import client
from auth.access_control import is_authorized
from models.model_manager import fetch_models
from storage.user_settings import get_user_model, set_user_model, get_user_system_prompt, set_user_system_prompt, reset_user_system_prompt
from storage.chat_history import clear_chat_history
from utils.decorators import require_auth, rate_limited, log_command, handle_errors
from config.help_texts import HELP_TEXTS
from config import DEFAULT_SYSTEM_PROMPT


@bot.message_handler(commands=["help", "start"])
@require_auth()
async def send_welcome(message):
    # Для админа показываем расширенную справку
    from auth.access_control import is_admin

    help_text = HELP_TEXTS["admin"] if is_admin(message) else HELP_TEXTS["user"]
    await bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["new"])
@require_auth()
@log_command
@handle_errors("❌ Не удалось очистить историю. Попробуйте позже.")
async def clear_history(message):
    success = clear_chat_history(message.chat.id)
    if success:
        await bot.reply_to(message, "✅ История чата очищена!")
    else:
        raise Exception("Failed to clear chat history")


@bot.message_handler(commands=["models"])
@require_auth()
@log_command
@handle_errors()
async def list_models(message):
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

    await bot.reply_to(message, models_list, parse_mode="Markdown")


@bot.message_handler(commands=["model"])
@require_auth()
@log_command
@handle_errors()
async def set_model(message):
    args = message.text.split("/model")[1].strip()
    if len(args) == 0:
        await bot.reply_to(
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
        await bot.reply_to(
            message,
            f"❌ Модель `{model_name}` не найдена.\n\nСписок моделей: /models",
            parse_mode="Markdown",
        )
        return

    set_user_model(message.chat.id, model_name)
    await bot.reply_to(
        message,
        f"✅ Модель изменена на: `{model_name}`",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["image"])
@require_auth()
@rate_limited
@log_command
@handle_errors("Произошла ошибка, попробуйте позже!")
async def image(message):
    prompt = message.text.split("/image")[1].strip()
    if len(prompt) == 0:
        await bot.reply_to(message, "Введите запрос после команды /image")
        return

    response = client.images.generate(
        prompt=prompt, n=1, size="1024x1024", model="dall-e-3"
    )
    image_url = response.data[0].url

    await bot.send_photo(
        message.chat.id,
        image_url,
        reply_to_message_id=message.message_id,
    )


@bot.message_handler(commands=["system_prompt"])
@require_auth()
@log_command
@handle_errors()
async def show_system_prompt(message):
    """Показать текущий system prompt"""
    user_prompt = get_user_system_prompt(message.chat.id)

    if user_prompt:
        response = f"🔧 *Ваш пользовательский system prompt:*\n\n```\n{user_prompt}\n```\n\n"
        response += "Используйте /reset_system_prompt для сброса к дефолтному"
    else:
        response = f"🔧 *Дефолтный system prompt:*\n\n```\n{DEFAULT_SYSTEM_PROMPT}\n```\n\n"
        response += "Используйте /set_system_prompt для установки своего промпта"

    await bot.reply_to(message, response, parse_mode="Markdown")


@bot.message_handler(commands=["set_system_prompt"])
@require_auth()
@log_command
@handle_errors()
async def set_system_prompt_command(message):
    """Установить пользовательский system prompt"""
    args = message.text.split("/set_system_prompt", 1)

    if len(args) < 2 or not args[1].strip():
        await bot.reply_to(
            message,
            "❌ Введите текст промпта после команды.\n\n"
            "Использование: /set_system_prompt <текст>\n\n"
            "Пример:\n"
            "/set_system_prompt Отвечай кратко и по делу. Используй эмодзи.",
            parse_mode="Markdown",
        )
        return

    prompt = args[1].strip()

    # Ограничение длины промпта (разумное ограничение)
    if len(prompt) > 2000:
        await bot.reply_to(
            message,
            f"❌ System prompt слишком длинный ({len(prompt)} символов).\n"
            "Максимальная длина: 2000 символов.",
            parse_mode="Markdown",
        )
        return

    set_user_system_prompt(message.chat.id, prompt)

    response = f"✅ System prompt установлен!\n\n*Ваш промпт:*\n```\n{prompt}\n```\n\n"
    response += "Используйте /system_prompt для просмотра\n"
    response += "Используйте /reset_system_prompt для сброса"

    await bot.reply_to(message, response, parse_mode="Markdown")


@bot.message_handler(commands=["reset_system_prompt"])
@require_auth()
@log_command
@handle_errors()
async def reset_system_prompt_command(message):
    """Сбросить system prompt к дефолтному"""
    was_reset = reset_user_system_prompt(message.chat.id)

    if was_reset:
        response = f"✅ System prompt сброшен к дефолтному!\n\n"
        response += f"*Дефолтный промпт:*\n```\n{DEFAULT_SYSTEM_PROMPT}\n```"
    else:
        response = "ℹ️ У вас уже используется дефолтный system prompt."

    await bot.reply_to(message, response, parse_mode="Markdown")
