"""
User management (registration, status tracking).
"""

from datetime import datetime
from config import ADMIN_CHAT_ID, ADMIN_USERNAME
from storage.base import S3Repository
from auth.validators import validate_username
from core.telegram import bot, app_logger


# Users database repository
users_db_repo = S3Repository(
    f"{ADMIN_CHAT_ID}_users.json",
    default_factory=lambda: {"users": {}}
)


def get_users_db():
    """Получить базу пользователей из S3"""
    return users_db_repo.get(ADMIN_CHAT_ID)


def save_users_db(users_db):
    """Сохранить базу пользователей в S3"""
    return users_db_repo.save(ADMIN_CHAT_ID, users_db)


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
