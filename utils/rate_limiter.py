"""
Rate limiting utilities.
"""

import time
from config import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW
from core.telegram import app_logger

# Global rate limit data
rate_limit_data = {}  # {chat_id: [timestamp1, timestamp2, ...]}


def check_rate_limit(chat_id):
    """
    Проверка rate limit для пользователя.
    Возвращает (allowed: bool, wait_time: int).
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
