"""
Text and photo message handlers.
"""

from core.telegram import bot, app_logger
from config import MAX_MESSAGE_LENGTH
from auth.access_control import is_authorized, is_admin
from utils.rate_limiter import check_rate_limit
from utils.typing_indicator import start_typing, stop_typing
from utils.messaging import send_long_message
from ai.processor import process_text_message


@bot.message_handler(func=lambda message: is_authorized(message), content_types=["text", "photo"])
def echo_message(message):
    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit: user={message.from_user.username}, chat_id={message.chat.id}")
            return

    start_typing(message.chat.id)

    try:
        text = message.text
        image_content = None
        has_photo = False

        photo = message.photo
        if photo is not None:
            has_photo = True
            photo = photo[0]
            file_info = bot.get_file(photo.file_id)
            image_content = bot.download_file(file_info.file_path)
            text = message.caption
            if text is None or len(text) == 0:
                text = "Что на картинке?"

        ai_response = process_text_message(text, message.chat.id, image_content)

        log_msg_type = "photo" if has_photo else "text"
        app_logger.info(
            f"Message processed: user={message.from_user.username}, chat_id={message.chat.id}, "
            f"type={log_msg_type}, prompt_length={len(text) if text else 0}, "
            f"response_length={len(ai_response) if ai_response else 0}"
        )
    except Exception as e:
        app_logger.error(f"Error processing message: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    stop_typing(message.chat.id)
    # Send with automatic splitting for long messages
    # Falls back to plain text on parse error
    try:
        send_long_message(message.chat.id, ai_response, reply_to_message=message, parse_mode="HTML")
    except Exception as e:
        if "can't parse entities" in str(e) or "Bad Request" in str(e):
            app_logger.warning(f"HTML parse error, sending as plain text: {e}")
            # Отправляем как обычный текст без форматирования
            if len(ai_response) <= MAX_MESSAGE_LENGTH:
                bot.reply_to(message, ai_response)
            else:
                # Split into chunks for plain text
                chunks = []
                current_chunk = ""
                for line in ai_response.split('\n'):
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

                for i, chunk in enumerate(chunks):
                    if i == 0:
                        bot.reply_to(message, chunk)
                    else:
                        bot.send_message(message.chat.id, chunk)
        else:
            raise
