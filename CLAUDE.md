# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Telegram AI Chat Bot** written in Python that integrates with OpenAI-compatible API and S3-compatible object storage. The bot provides multi-modal AI capabilities including text chat, image analysis/generation, and voice interaction (transcription + text-to-speech).

## Architecture

**Single-file polling bot design**:
- `bot.py` contains all bot logic (~450 lines)
- State is maintained externally in S3-compatible object storage (MinIO, Yandex, AWS)
- Telegram polling mode (not webhook)
- Access control via admin approval system (not whitelist)
- Dynamic model fetching from API

### Application Flow

```
Telegram Polling → Authentication Check → Message Processing
                              ↓
              ┌───────────────┴───────────────┐
              ↓                               ↓
        Text/Photo Messages              Voice Messages
              ↓                               ↓
    process_text_message()          Whisper → TTS Response
   (get_user_model() → fetch_models())
              ↓
    OpenAI-compatible API
   (user-selected model)
              ↓
    S3 Storage (save/retrieve)
   - {chat_id}.json → chat history
   - {chat_id}_settings.json → user model
   - {ADMIN_CHAT_ID}_users.json → user access control
              ↓
        Telegram Response (Markdown)
```

### Message Type Handlers

| Handler | Content Types | Model Used | Features |
|---------|--------------|------------|----------|
| `echo_message()` | text, photo | User model / gpt-4-vision-preview | Image analysis via base64 |
| `voice()` | voice (audio/ogg) | whisper-1 → tts-1-hd | Transcribes, processes, returns audio |
| `image()` | /image command | dall-e-3 | Generates images from prompts |

### Bot Commands

**User commands:**
| Command | Description |
|---------|-------------|
| `/start`, `/help` | Welcome message (admin sees extended help) |
| `/models` | List available models (grouped by `owned_by`) |
| `/model <name>` | Select AI model for text chats |
| `/new` | Clear chat history |
| `/image <prompt>` | Generate image via DALL-E 3 |

**Admin commands:**
| Command | Description |
|---------|-------------|
| `/users` | List all users with statuses (pending/approved/denied) |
| `/approve <username>` | Approve user access |
| `/deny <username>` | Deny user access |

### Key Functions

**User Management:**
- **`get_users_db()`** - Fetches users database from S3
- **`save_users_db(users_db)`** - Saves users database to S3
- **`register_user(username, chat_id)`** - Registers new user with `pending` status, notifies admin
- **`get_user_status(username)`** - Returns user status: `approved`, `pending`, `denied`, or `None`
- **`set_user_status(username, status)`** - Updates user status in S3
- **`is_authorized(message)`** - Checks access via admin approval system
- **`is_admin(message)`** - Checks if user is admin (ADMIN_USERNAME)

**Model & AI:**
- **`fetch_models()`** - Fetches models from `{OPENAI_BASE_URL}/models`, groups by `owned_by`
- **`get_user_model(chat_id)`** - Retrieves user's selected model from S3, defaults to `glm-4.7`
- **`set_user_model(chat_id, model)`** - Stores user's model preference in S3
- **`process_text_message(text, chat_id, image_content)`** - Core AI logic, uses user model for text, `gpt-4-vision-preview` for images

**S3 & Infrastructure:**
- **`get_s3_client()`** - Creates S3 client using `MINIO_ENDPOINT` or defaults to Yandex Cloud
- **`handler(event, context)`** - AWS Lambda entry point (optional, for webhook deployment)

## Environment Setup

Required environment variables in `.env`:

```bash
# Telegram
TG_BOT_TOKEN=<telegram_bot_token>

# Administrator (has full access, approves others)
ADMIN_USERNAME=R6DJO
ADMIN_CHAT_ID=1212054

# OpenAI-compatible API
OPENAI_API_KEY=<api_key>
OPENAI_BASE_URL=<base_url>  # http://localhost:8317/v1 or default proxy

# S3-compatible storage
S3_KEY_ID=<access_key>
S3_KEY_SECRET=<secret_key>
S3_BUCKET=<bucket_name>
MINIO_ENDPOINT=<endpoint_url>  # Optional, defaults to Yandex Cloud

# MinIO (for docker-compose only)
MINIO_ROOT_USER=<admin_user>
MINIO_ROOT_PASSWORD=<admin_password>
```

Note: The `.env` file is auto-loaded via `python-dotenv`.

## Development Commands

```bash
# Setup virtual environment
source venv/bin/activate
pip install -r requirements.txt

# Start all services (MinIO + Bot)
docker-compose up -d

# View logs
tail -f logs/bot.log
docker logs -f telegram-bot

# Stop all services
docker-compose down

# Run bot locally (for development)
docker-compose up -d minio minio-setup
python bot.py
```

## Architecture Notes

**User Authorization Flow:**
1. New user sends message → `register_user()` creates entry with status `pending`
2. Admin receives notification with `/approve` and `/deny` commands
3. Admin approves/denies → user gets notified, status updated in S3
4. Pending users see "waiting for approval" message
5. Denied users see "access denied" message
6. Admin always has access (bypasses `is_authorized()` check)

User database structure in S3 (`{ADMIN_CHAT_ID}_users.json`):
```json
{
  "users": {
    "username": {
      "chat_id": 12345,
      "status": "approved" | "pending" | "denied",
      "first_seen": "2025-02-01T12:34:56",
      "username": "Username"
    }
  }
}
```

**Model Management**: Models are fetched dynamically from API endpoint `{OPENAI_BASE_URL}/models`. Response format: `{"data": [{"id": "model-name", "owned_by": "vendor"}, ...]}`. Models are grouped by `owned_by` for display in `/models` command.

**State Management**:
- Chat history: `{chat_id}.json` — array of message objects with `role` and `content`
- User settings: `{chat_id}_settings.json` — contains selected `model`
- Users database: `{ADMIN_CHAT_ID}_users.json` — contains all users with statuses
- Only text messages are persisted; images and voice are not saved to history

**Logging**: All requests and responses logged to `logs/bot.log` with timestamps:
- User messages with chat_id, username, prompt length
- AI responses with model, response length
- Model selection changes
- Errors with full context
- New user registrations

**Error Recovery**: On `BadRequestError` from API (typically context overflow), the bot clears chat history via `clear_history_for_chat()` and retries the request.

**Threading**: Bot runs with `threaded=False`. Typing indicator uses background thread that polls every 4 seconds.

**Markdown**: All bot responses use `parse_mode="Markdown"` for formatted output.

## Docker Deployment

Project uses Docker Compose with three services:
- **bot** - Python Alpine container, mounts `./logs:/app/logs`
- **minio** - S3-compatible storage
- **minio-setup** - One-shot container that creates bucket and user

Bot connects to MinIO via internal Docker network (`http://minio:9000`).

All services use `restart: unless-stopped` for auto-restart (except manual `docker-compose stop`).

## MinIO Setup

Project uses Docker Compose for MinIO with auto-setup:
- Creates bucket from `S3_BUCKET` env var
- Creates user from `S3_KEY_ID` / `S3_KEY_SECRET`
- Assigns `readwrite` policy to user

See `MINIO_SETUP.md` for detailed documentation.

## Default Configuration

- **Admin**: `ADMIN_USERNAME=R6DJO`, `ADMIN_CHAT_ID=1212054`
- **Default model**: `glm-4.7`
- **Vision model**: `gpt-4-vision-preview` (forced for images)
- **TTS voice**: `nova` (model `tts-1-hd`, format `opus`)
- **Image generation**: `dall-e-3`, size `1024x1024`
- **User status**: `pending` for new users, requires admin approval
