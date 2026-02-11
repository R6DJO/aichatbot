"""
Text and photo message handlers.
"""

from core.telegram import bot, app_logger
from auth.access_control import is_authorized, is_admin, should_process_message
from utils.rate_limiter import check_rate_limit
from utils.typing_indicator import start_typing, stop_typing
from utils.messaging import send_long_message
from ai.processor import process_text_message


@bot.message_handler(func=should_process_message, content_types=["text", "photo"])
async def echo_message(message):
    # Full authorization check with user feedback
    if not await is_authorized(message):
        return

    # Check rate limit (skip for admin)
    if not is_admin(message):
        allowed, wait_time = check_rate_limit(message.chat.id)
        if not allowed:
            await bot.reply_to(
                message,
                f"⏱️ Слишком много запросов! Пожалуйста, подождите {wait_time} секунд.",
            )
            app_logger.warning(f"Rate limit hit: user={message.from_user.username}, chat_id={message.chat.id}")
            return

    await start_typing(message.chat.id)

    try:
        text = message.text
        image_content = None
        has_photo = False

        photo = message.photo
        if photo is not None:
            has_photo = True
            photo = photo[0]
            file_info = await bot.get_file(photo.file_id)
            image_content = await bot.download_file(file_info.file_path)
            text = message.caption
            if text is None or len(text) == 0:
                text = "Что на картинке?"

        ai_response = await process_text_message(text, message.chat.id, image_content)

        log_msg_type = "photo" if has_photo else "text"
        app_logger.info(
            f"Message processed: user={message.from_user.username}, chat_id={message.chat.id}, "
            f"type={log_msg_type}, prompt_length={len(text) if text else 0}, "
            f"response_length={len(ai_response) if ai_response else 0}"
        )
    except Exception as e:
        app_logger.error(f"Error processing message: user={message.from_user.username}, chat_id={message.chat.id}, error={str(e)}")
        await bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    await stop_typing(message.chat.id)

    # Send with automatic splitting and parse error recovery
    await send_long_message(message.chat.id, ai_response, reply_to_message=message, parse_mode="HTML")
