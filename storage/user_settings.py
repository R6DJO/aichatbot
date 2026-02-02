"""
User settings storage operations.
"""

import json
from config import S3_BUCKET
from storage.s3_client import get_s3_client
from core.telegram import app_logger


def get_user_settings(chat_id):
    """Получить настройки пользователя из S3"""
    s3client = get_s3_client()
    try:
        response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}_settings.json"
        )
        return json.loads(response["Body"].read())
    except:
        return {}


def save_user_settings(chat_id, settings):
    """Сохранить настройки пользователя в S3"""
    s3client = get_s3_client()
    try:
        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}_settings.json",
            Body=json.dumps(settings),
        )
    except Exception as e:
        app_logger.error(f"Error saving user settings: {e}")


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
