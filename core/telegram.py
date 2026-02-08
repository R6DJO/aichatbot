"""
Telegram bot initialization and logging setup.
"""

import logging
from telebot.async_telebot import AsyncTeleBot
from config import TG_BOT_TOKEN

# Setup telebot logger
logger = logging.getLogger('telebot')
logger.setLevel(logging.INFO)

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

# Create bot instance (async version for concurrent request handling)
bot = AsyncTeleBot(TG_BOT_TOKEN)
