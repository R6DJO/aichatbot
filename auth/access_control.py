"""
Access control (authorization checks).
"""

from config import ADMIN_USERNAME
from auth.user_manager import register_user, get_user_status


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
