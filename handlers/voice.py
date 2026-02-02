"""
Voice message handler.
"""

import os
import uuid
import tempfile
from telebot.types import InputFile
from core.telegram import bot, app_logger
from core.openai_client import client
from auth.access_control import is_authorized, is_admin
from utils.rate_limiter import check_rate_limit
from ai.processor import process_text_message


@bot.message_handler(
    func=lambda msg: is_authorized(msg) and msg.voice.mime_type == "audio/ogg", content_types=["voice"]
)
def voice(message):
    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit (voice): user={message.from_user.username}, chat_id={message.chat.id}")
            return

    app_logger.info(f"Voice message received: user={message.from_user.username}, chat_id={message.chat.id}")

    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    # Create unique temporary file to avoid race conditions
    temp_file = None
    try:
        response = client.audio.transcriptions.create(
            file=("file.ogg", downloaded_file, "audio/ogg"),
            model="whisper-1",
        )
        transcribed_text = response.text
        app_logger.info(f"Voice transcribed: user={message.from_user.username}, chat_id={message.chat.id}, text='{transcribed_text[:100]}...'")

        ai_response = process_text_message(transcribed_text, message.chat.id)
        ai_voice_response = client.audio.speech.create(
            input=ai_response,
            voice="nova",
            model="tts-1-hd",
            response_format="opus",
        )

        # Use unique filename to avoid race conditions between different users
        temp_file = os.path.join(tempfile.gettempdir(), f"ai_voice_{message.chat.id}_{uuid.uuid4().hex}.ogg")
        with open(temp_file, "wb") as f:
            f.write(ai_voice_response.content)

        with open(temp_file, "rb") as f:
            bot.send_voice(
                message.chat.id,
                voice=InputFile(f),
                reply_to_message_id=message.message_id,
            )
    except Exception as e:
        app_logger.error(f"Voice processing failed: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                app_logger.warning(f"Failed to remove temp file {temp_file}: {e}")
