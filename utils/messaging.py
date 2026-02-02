"""
Messaging utilities for sending long messages.
"""

from core.telegram import bot
from config import MAX_MESSAGE_LENGTH
from utils.formatters import markdown_to_html


def send_long_message(chat_id, text, reply_to_message=None, parse_mode="HTML"):
    """Send a message, splitting it if it's too long (Telegram limit: 4096 chars)."""

    # Конвертируем markdown в HTML если нужно
    if parse_mode == "HTML":
        text = markdown_to_html(text)

    if len(text) <= MAX_MESSAGE_LENGTH:
        if reply_to_message:
            bot.reply_to(reply_to_message, text, parse_mode=parse_mode)
        else:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
    else:
        # Split into chunks
        chunks = []
        current_chunk = ""
        for line in text.split('\n'):
            # If adding this line would exceed limit, save current chunk
            if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                if current_chunk:
                    current_chunk += '\n' + line
                else:
                    current_chunk = line
        if current_chunk:
            chunks.append(current_chunk)

        # Send each chunk
        for i, chunk in enumerate(chunks):
            if reply_to_message and i == 0:
                bot.reply_to(reply_to_message, chunk, parse_mode=parse_mode)
            else:
                bot.send_message(chat_id, chunk, parse_mode=parse_mode)
