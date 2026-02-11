"""
Admin command handlers.
"""

from core.telegram import bot, app_logger
from auth.user_manager import get_users_db, set_user_status
from utils.decorators import require_auth, log_command, handle_errors
import ai.processor  # For accessing mcp_manager


@bot.message_handler(commands=["users"])
@require_auth(admin_only=True)
@log_command
@handle_errors()
async def list_users(message):
    """Список всех пользователей (только для админа)"""
    users_db = get_users_db()
    users = users_db.get("users", {})

    if not users:
        await bot.reply_to(message, "👥 Пользователей пока нет.")
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

    await bot.reply_to(message, text, parse_mode="Markdown")


async def update_user_access(message, username_arg: str, new_status: str, command_name: str):
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
        await bot.reply_to(message, "❌ Некорректное имя пользователя")
        return

    # Сообщения для разных статусов
    status_messages = {
        "approved": {
            "user": "✅ Доступ разрешён!\n\nАдминистратор одобрил вашу заявку. Теперь вы можете использовать бота.",
            "admin": f"✅ Пользователь @{username} одобрен.",
            "log": "approved"
        },
        "denied": {
            "user": "❌ Доступ запрещён!\n\nАдминистратор отклонил вашу заявку.",
            "admin": f"❌ Пользователю @{username} запрещён доступ.",
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
                await bot.send_message(chat_id, messages["user"])
            except Exception as e:
                app_logger.warning(f"Failed to notify user {username}: {e}")

        # Уведомляем админа
        await bot.reply_to(message, messages["admin"])
        app_logger.info(f"User {messages['log']}: {username} by admin {message.from_user.username}")
    else:
        # Пользователь не найден
        await bot.reply_to(message, f"❌ Пользователь @{username} не найден.")


@bot.message_handler(commands=["approve"])
@require_auth(admin_only=True)
@handle_errors()
async def approve_user(message):
    """Одобрить пользователя (только для админа)"""
    args = message.text.split("/approve", 1)[1].strip()
    if not args:
        await bot.reply_to(message, "Используйте: `/approve <username>`", parse_mode="Markdown")
        return

    await update_user_access(message, args, "approved", "approve")


@bot.message_handler(commands=["deny"])
@require_auth(admin_only=True)
@handle_errors()
async def deny_user(message):
    """Запретить пользователя (только для админа)"""
    args = message.text.split("/deny", 1)[1].strip()
    if not args:
        await bot.reply_to(message, "Используйте: `/deny <username>`", parse_mode="Markdown")
        return

    await update_user_access(message, args, "denied", "deny")


@bot.message_handler(commands=["mcpstatus"])
@require_auth(admin_only=True)
@log_command
@handle_errors("❌ Error getting MCP status.")
async def mcp_status(message):
    if not ai.processor.mcp_manager:
        await bot.reply_to(message, "🔧 MCP Manager not initialized.")
        return

    status = ai.processor.mcp_manager.get_server_status()

    status_text = "🔧 *MCP Server Status:*\n\n"
    for server_name, server_status in status.items():
        emoji = "✅" if server_status == "connected" else "❌"
        status_text += f"{emoji} *{server_name}*: `{server_status}`\n"

    await bot.reply_to(message, status_text, parse_mode="Markdown")
