"""
Username validation utilities.
"""

import re


def validate_username(username: str) -> bool:
    """
    Проверка валидности Telegram username.

    Требования:
    - Не пустой
    - Длина от 5 до 32 символов (Telegram ограничение)
    - Только латинские буквы, цифры и подчеркивание
    - Не может начинаться с цифры
    """
    if not username:
        return False

    if len(username) < 5 or len(username) > 32:
        return False

    # Regex: начинается с буквы или подчеркивания, далее буквы/цифры/подчеркивания
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', username):
        return False

    return True
