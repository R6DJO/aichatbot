"""
Messaging utilities for sending long messages.
"""

from core.telegram import bot, app_logger
from config import MAX_MESSAGE_LENGTH
from utils.formatters import markdown_to_html


def send_long_message(chat_id, text, reply_to_message=None, parse_mode="HTML"):
    """
    Send a message, splitting it if it's too long (Telegram limit: 4096 chars).

    Automatically falls back to plain text if parse errors occur.

    Args:
        chat_id: Telegram chat ID
        text: Message text
        reply_to_message: Message to reply to (optional)
        parse_mode: Parse mode ("HTML", "Markdown", or None for plain text)
    """
    # Convert markdown to HTML if needed
    if parse_mode == "HTML":
        text = markdown_to_html(text)

    # Try with formatting first
    if parse_mode:
        try:
            _send_message_chunks(chat_id, text, reply_to_message, parse_mode)
            return
        except Exception as e:
            if "can't parse entities" in str(e) or "Bad Request" in str(e):
                app_logger.warning(f"Parse error with {parse_mode}, falling back to plain text: {e}")
                # Fall through to plain text
                parse_mode = None
            else:
                raise

    # Plain text fallback (or if parse_mode was None from the start)
    _send_message_chunks(chat_id, text, reply_to_message, parse_mode=None)


def _send_message_chunks(chat_id, text, reply_to_message, parse_mode):
    """
    Internal function to send message chunks.

    Args:
        chat_id: Telegram chat ID
        text: Message text (already formatted if needed)
        reply_to_message: Message to reply to (optional)
        parse_mode: Parse mode (or None for plain text)
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        # Send single message
        if reply_to_message:
            bot.reply_to(reply_to_message, text, parse_mode=parse_mode)
        else:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
    else:
        # Split into chunks
        chunks = _split_text_into_chunks(text, MAX_MESSAGE_LENGTH)

        # Send each chunk
        for i, chunk in enumerate(chunks):
            if reply_to_message and i == 0:
                bot.reply_to(reply_to_message, chunk, parse_mode=parse_mode)
            else:
                bot.send_message(chat_id, chunk, parse_mode=parse_mode)


def _split_text_into_chunks(text, max_length):
    """
    Split text into chunks by lines, respecting max_length.

    Args:
        text: Text to split
        max_length: Maximum length per chunk

    Returns:
        List of text chunks
    """
    chunks = []
    current_chunk = ""

    for line in text.split('\n'):
        # If adding this line would exceed limit, save current chunk
        if len(current_chunk) + len(line) + 1 > max_length:
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

    return chunks
