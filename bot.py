import logging
import telebot
import os
import openai
import json
import boto3
import time
import threading
import base64
from telebot.types import InputFile
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_BOT_CHATS = os.environ.get("TG_BOT_CHATS").lower().split(",")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1")
S3_KEY_ID = os.environ.get("S3_KEY_ID")
S3_KEY_SECRET = os.environ.get("S3_KEY_SECRET")
S3_BUCKET = os.environ.get("S3_BUCKET")


logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)

client = openai.Client(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)


def get_s3_client():
    session = boto3.session.Session(
        aws_access_key_id=S3_KEY_ID, aws_secret_access_key=S3_KEY_SECRET
    )
    # Используй переменную окружения MINIO_ENDPOINT для своего S3
    endpoint_url = os.environ.get("MINIO_ENDPOINT", "https://storage.yandexcloud.net")
    return session.client(
        service_name="s3", endpoint_url=endpoint_url
    )


is_typing = False

# Проверка доступа: только авторизованные пользователи
def is_authorized(message):
    if message.from_user.username is None:
        return False
    return message.from_user.username.lower() in TG_BOT_CHATS

def start_typing(chat_id):
    global is_typing
    is_typing = True
    typing_thread = threading.Thread(target=typing, args=(chat_id,))
    typing_thread.start()

def typing(chat_id):
    global is_typing
    while is_typing:
        bot.send_chat_action(chat_id, "typing")
        time.sleep(4)

def stop_typing():
    global is_typing
    is_typing = False


@bot.message_handler(commands=["help", "start"])
def send_welcome(message):
    if not is_authorized(message):
        bot.reply_to(message, "У вас нет доступа к этому боту.")
        return
    bot.reply_to(
        message,
        ("Привет! Я ChatGPT бот. Спроси меня что-нибудь!"),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["new"])
def clear_history(message):
    if not is_authorized(message):
        return
    clear_history_for_chat(message.chat.id)
    bot.reply_to(message, "История чата очищена!")


@bot.message_handler(commands=["image"])
def image(message):
    if not is_authorized(message):
        return
    prompt = message.text.split("/image")[1].strip()
    if len(prompt) == 0:
        bot.reply_to(message, "Введите запрос после команды /image")
        return

    try:
        response = client.images.generate(
            prompt=prompt, n=1, size="1024x1024", model="dall-e-3"
        )
    except:
        bot.reply_to(message, "Произошла ошибка, попробуйте позже!")
        return

    bot.send_photo(
        message.chat.id,
        response.data[0].url,
        reply_to_message_id=message.message_id,
    )


@bot.message_handler(func=lambda message: is_authorized(message), content_types=["text", "photo"])
def echo_message(message):
    start_typing(message.chat.id)

    try:
        text = message.text
        image_content = None

        photo = message.photo
        if photo is not None:
            photo = photo[0]
            file_info = bot.get_file(photo.file_id)
            image_content = bot.download_file(file_info.file_path)
            text = message.caption
            if text is None or len(text) == 0:
                text = "Что на картинке?"

        ai_response = process_text_message(text, message.chat.id, image_content)
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    stop_typing()
    bot.reply_to(message, ai_response, parse_mode="Markdown")


@bot.message_handler(
    func=lambda msg: is_authorized(msg) and msg.voice.mime_type == "audio/ogg", content_types=["voice"]
)
def voice(message):
    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    try:
        response = client.audio.transcriptions.create(
            file=("file.ogg", downloaded_file, "audio/ogg"),
            model="whisper-1",
        )
        ai_response = process_text_message(response.text, message.chat.id)
        ai_voice_response = client.audio.speech.create(
            input=ai_response,
            voice="nova",
            model="tts-1-hd",
            response_format="opus",
        )
        with open("/tmp/ai_voice_response.ogg", "wb") as f:
            f.write(ai_voice_response.content)
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка, попробуйте позже! {e}")
        return

    with open("/tmp/ai_voice_response.ogg", "rb") as f:
        bot.send_voice(
            message.chat.id,
            voice=InputFile(f),
            reply_to_message_id=message.message_id,
        )


def process_text_message(text, chat_id, image_content=None) -> str:
    model = "glm-4.7"
    max_tokens = None

    # read current chat history
    s3client = get_s3_client()
    history = []
    try:
        history_object_response = s3client.get_object(
            Bucket=S3_BUCKET, Key=f"{chat_id}.json"
        )
        history = json.loads(history_object_response["Body"].read())
    except:
        pass

    history_text_only = history.copy()
    history_text_only.append({"role": "user", "content": text})

    if image_content is not None:
        model = "gpt-4-vision-preview"
        max_tokens = 4000
        base64_image_content = base64.b64encode(image_content).decode("utf-8")
        base64_image_content = f"data:image/jpeg;base64,{base64_image_content}"
        history.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": base64_image_content}},
                ],
            }
        )
    else:
        history.append({"role": "user", "content": text})

    try:
        chat_completion = client.chat.completions.create(
            model=model, messages=history, max_tokens=max_tokens
        )
    except Exception as e:
        if type(e).__name__ == "BadRequestError":
            clear_history_for_chat(chat_id)
            return process_text_message(text, chat_id)
        else:
            raise e

    ai_response = chat_completion.choices[0].message.content
    history_text_only.append({"role": "assistant", "content": ai_response})

    # save current chat history
    s3client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{chat_id}.json",
        Body=json.dumps(history_text_only),
    )

    return ai_response


def clear_history_for_chat(chat_id):
    try:
        s3client = get_s3_client()
        s3client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{chat_id}.json",
            Body=json.dumps([]),
        )
    except:
        pass


# AWS Lambda handler для webhook-режима (опционально)
def handler(event, context):
    message = json.loads(event["body"])
    update = telebot.types.Update.de_json(message)

    if (
        update.message is not None
        and update.message.from_user.username.lower() in TG_BOT_CHATS
    ):
        try:
            bot.process_new_updates([update])
        except Exception as e:
            print(e)

    return {
        "statusCode": 200,
        "body": "ok",
    }


# Запуск бота в режиме polling
if __name__ == "__main__":
    print("Бот запущен в режиме polling...")
    bot.infinity_polling()
