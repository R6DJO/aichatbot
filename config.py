"""
Configuration module for Telegram AI Chat Bot.
Contains all environment variables and constants.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ============ Environment Variables ============

# Telegram
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID"))

# OpenAI-compatible API
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")

# S3-compatible storage
S3_KEY_ID = os.environ.get("S3_KEY_ID")
S3_KEY_SECRET = os.environ.get("S3_KEY_SECRET")
S3_BUCKET = os.environ.get("S3_BUCKET")

# ============ Constants ============

# Rate limiting (requests per minute)
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60  # seconds

# Chat history limits
MAX_HISTORY_LENGTH = 50  # Maximum number of messages to keep in history

# Message and token limits
MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, use safe margin
MAX_VISION_TOKENS = 4000  # Max tokens for vision model responses

# MCP configuration
MCP_TOOL_TIMEOUT_SECONDS = 30  # Timeout for tool execution
MCP_MAX_ITERATIONS = 5  # Maximum tool call iterations to prevent loops

# Typing indicator
TYPING_INTERVAL_SECONDS = 4  # Interval for sending typing action
