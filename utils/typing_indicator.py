"""
Typing indicator management.
"""

import asyncio
from config import TYPING_INTERVAL_SECONDS
from core.telegram import bot, app_logger

# Async task management
typing_tasks = {}  # {chat_id: asyncio.Task}


async def start_typing(chat_id):
    """Start typing indicator for a specific chat"""
    if chat_id in typing_tasks:
        # Already typing for this chat
        return

    # Create and store the typing task
    task = asyncio.create_task(typing_loop(chat_id))
    typing_tasks[chat_id] = task


async def typing_loop(chat_id):
    """Send typing action in a loop"""
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id, "typing")
            except Exception as e:
                app_logger.error(f"Error sending typing action for chat {chat_id}: {e}")
                break
            await asyncio.sleep(TYPING_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        # Task was cancelled by stop_typing
        pass


async def stop_typing(chat_id):
    """Stop typing indicator for a specific chat"""
    if chat_id in typing_tasks:
        task = typing_tasks[chat_id]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        del typing_tasks[chat_id]
