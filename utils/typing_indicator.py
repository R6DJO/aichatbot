"""
Typing indicator management.
"""

import threading
from config import TYPING_INTERVAL_SECONDS
from core.telegram import bot, app_logger

# Thread-safe typing state management
typing_states = {}  # {chat_id: threading.Event()}


def start_typing(chat_id):
    """Start typing indicator for a specific chat (thread-safe)"""
    if chat_id in typing_states:
        # Already typing for this chat
        return

    stop_event = threading.Event()
    typing_states[chat_id] = stop_event
    typing_thread = threading.Thread(target=typing, args=(chat_id, stop_event), daemon=True)
    typing_thread.start()


def typing(chat_id, stop_event):
    """Send typing action until stop_event is set"""
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception as e:
            app_logger.error(f"Error sending typing action for chat {chat_id}: {e}")
            break
        stop_event.wait(timeout=TYPING_INTERVAL_SECONDS)


def stop_typing(chat_id):
    """Stop typing indicator for a specific chat"""
    if chat_id in typing_states:
        typing_states[chat_id].set()
        del typing_states[chat_id]
