"""
Access control (authorization checks).
"""

from config import ADMIN_USERNAME
from auth.user_manager import register_user, get_user_status
from core.telegram import bot, app_logger


def is_authorized(message):
    """Проверка доступа к боту"""
    username = message.from_user.username

    if not username:
        app_logger.warning(f"Authorization denied: missing username, chat_id={message.chat.id}")
        bot.reply_to(
            message,
            "❌ Установите username в Telegram, чтобы использовать бота.\n\nОткройте настройки Telegram → Изменить имя пользователя",
        )
        return False

    # Админ всегда имеет доступ
    if username.lower() == ADMIN_USERNAME.lower():
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
