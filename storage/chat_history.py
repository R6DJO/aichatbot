"""
Chat history storage operations.
"""

from storage.base import S3Repository


# Chat history repository: stores chat history as list of messages
chat_history_repo = S3Repository("{id}.json", default_factory=list)


def get_chat_history(chat_id):
    """Получить историю чата из S3"""
    return chat_history_repo.get(str(chat_id))


def save_chat_history(chat_id, history):
    """Сохранить историю чата в S3"""
    return chat_history_repo.save(str(chat_id), history)


def clear_chat_history(chat_id):
    """Очистить историю чата"""
    return chat_history_repo.save(str(chat_id), [])
