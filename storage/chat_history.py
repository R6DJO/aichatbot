"""
Chat history storage operations.
"""

import json
from config import S3_BUCKET
from storage.s3_client import get_s3_client
from core.telegram import app_logger


def get_chat_history(chat_id):
    """Получить историю чата из S3"""
    s3client = get_s3_client()
    try:
        history_object_response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}.json"
        )
        return json.loads(history_object_response["Body"].read())
    except s3client.exceptions.NoSuchKey:
        return []
    except Exception as exc:
        app_logger.error(
            f"Failed to get chat history: chat_id={chat_id}, bucket={S3_BUCKET}, key={chat_id}.json, error={exc}"
        )
        raise


def save_chat_history(chat_id, history):
    """Сохранить историю чата в S3"""
    s3client = get_s3_client()
    s3client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{chat_id}.json",
        Body=json.dumps(history),
    )


def clear_chat_history(chat_id):
    """Очистить историю чата"""
    try:
        s3client = get_s3_client()
        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}.json",
            Body=json.dumps([]),
        )
        return True
    except Exception as exc:
        app_logger.error(
            f"Failed to clear chat history: chat_id={chat_id}, bucket={S3_BUCKET}, key={chat_id}.json, error={exc}"
        )
        return False
