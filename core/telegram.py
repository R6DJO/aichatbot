"""
Telegram bot initialization and logging setup.
"""

import logging
import telebot
from config import TG_BOT_TOKEN

# Setup telebot logger
logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

# Настройка логирования (только в stdout для Docker)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# Application logger
app_logger = logging.getLogger(__name__)

# Create bot instance (threaded=False as per original design)
bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)
