"""
Decorators for command handlers.

Provides reusable decorators for:
- Authorization checks (@require_auth)
- Rate limiting (@rate_limited)
- Command logging (@log_command)
- Error handling (@handle_errors)

All decorators support async functions.
"""

from functools import wraps
from core.telegram import bot, app_logger
from auth.access_control import is_authorized, is_admin
from auth.validators import validate_username
from auth.user_manager import get_user_status
from utils.rate_limiter import check_rate_limit
from config.help_texts import HELP_TEXTS


def require_auth(admin_only=False):
    """
    Decorator to require authorization (async-compatible).

    Args:
        admin_only: If True, only admin can access (default: False)

    Usage:
        @require_auth()           # Any authorized user
        @require_auth(admin_only=True)  # Admin only
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message):
            # Admin check
            if admin_only and not is_admin(message):
                await bot.reply_to(message, "❌ Эта команда доступна только администратору.")
                return

            # Regular authorization check
            if not await is_authorized(message):
                # For help/start commands, we want to show detailed error messages
                # For other commands, is_authorized already handles the response
                if func.__name__ in ['send_welcome', 'help_command']:
                    username = message.from_user.username
                    status = get_user_status(username)

                    # Invalid username check
                    if not username or not validate_username(username):
                        await bot.reply_to(message, HELP_TEXTS["errors"]["invalid_username"])
                        return

                    if status == "pending":
                        await bot.reply_to(message, HELP_TEXTS["errors"]["pending"])
                        return
                    elif status == "denied":
                        await bot.reply_to(message, HELP_TEXTS["errors"]["denied"])
                        return
                    else:
                        await bot.reply_to(message, HELP_TEXTS["errors"]["no_access"])
                return

            return await func(message)
        return wrapper
    return decorator


def rate_limited(func):
    """
    Decorator to apply rate limiting (async-compatible).

    Admins bypass rate limits automatically.

    Usage:
        @rate_limited
        async def my_handler(message):
            ...
    """
    @wraps(func)
    async def wrapper(message):
        if not is_admin(message):
            allowed, wait_time = check_rate_limit(message.chat.id)
            if not allowed:
                await bot.reply_to(
                    message,
                    f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд."
                )
                command = message.text.split()[0] if message.text else "unknown"
                app_logger.warning(
                    f"Rate limit hit ({command}): user={message.from_user.username}, "
                    f"chat_id={message.chat.id}"
                )
                return

        return await func(message)
    return wrapper


def log_command(func):
    """
    Decorator to log command execution (async-compatible).

    Logs: command name, username, and chat_id

    Usage:
        @log_command
        async def my_handler(message):
            ...
    """
    @wraps(func)
    async def wrapper(message):
        command = message.text.split()[0] if message.text else "unknown"
        username = message.from_user.username if message.from_user else "unknown"
        app_logger.info(
            f"Command {command}: user={username}, chat_id={message.chat.id}"
        )
        return await func(message)
    return wrapper


def handle_errors(error_message="Произошла ошибка, попробуйте позже!"):
    """
    Decorator to handle exceptions (async-compatible).

    Args:
        error_message: Custom error message to show user (default: generic error)

    Usage:
        @handle_errors()
        @handle_errors("Custom error message")
        async def my_handler(message):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message):
            try:
                return await func(message)
            except Exception as e:
                username = message.from_user.username if message.from_user else "unknown"
                app_logger.error(
                    f"Error in {func.__name__}: user={username}, "
                    f"chat_id={message.chat.id}, error={str(e)}"
                )
                await bot.reply_to(message, error_message)
        return wrapper
    return decorator
