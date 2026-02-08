"""
User settings storage operations.
"""

from storage.base import S3Repository


# User settings repository: stores user preferences as dict
user_settings_repo = S3Repository("{id}_settings.json", default_factory=dict)


def get_user_settings(chat_id):
    """Получить настройки пользователя из S3"""
    return user_settings_repo.get(str(chat_id))


def save_user_settings(chat_id, settings):
    """Сохранить настройки пользователя в S3"""
    return user_settings_repo.save(str(chat_id), settings)


def get_user_model(chat_id):
    """Получить выбранную модель пользователя или дефолтную"""
    settings = get_user_settings(chat_id)
    return settings.get("model", "glm-4.7")


def set_user_model(chat_id, model):
    """Сохранить выбранную модель пользователя"""
    settings = get_user_settings(chat_id)
    settings["model"] = model
    save_user_settings(chat_id, settings)


def should_use_mcp_for_user(chat_id):
    """Check if MCP tools are enabled for this user"""
    settings = get_user_settings(chat_id)
    return settings.get("mcp_enabled", True)  # Default: enabled


def set_mcp_for_user(chat_id, enabled):
    """Enable/disable MCP tools for a user"""
    settings = get_user_settings(chat_id)
    settings["mcp_enabled"] = enabled
    save_user_settings(chat_id, settings)


def get_user_system_prompt(chat_id):
    """Получить пользовательский system prompt или None"""
    settings = get_user_settings(chat_id)
    return settings.get("system_prompt", None)


def set_user_system_prompt(chat_id, prompt):
    """Установить пользовательский system prompt"""
    settings = get_user_settings(chat_id)
    settings["system_prompt"] = prompt
    save_user_settings(chat_id, settings)


def reset_user_system_prompt(chat_id):
    """Сбросить пользовательский system prompt к дефолтному"""
    settings = get_user_settings(chat_id)
    if "system_prompt" in settings:
        del settings["system_prompt"]
        save_user_settings(chat_id, settings)
        return True
    return False
