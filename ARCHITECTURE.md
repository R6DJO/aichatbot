# Architecture Documentation

## Overview

Telegram AI Chat Bot использует **модульную архитектуру** для разделения ответственности, улучшения читаемости кода и упрощения тестирования.

## Refactoring Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Main file lines | 1385 | 47 | -97% |
| Number of files | 1 | 19+ | +1800% |
| Packages | 0 | 7 | - |
| Testability | Low | High | ++ |
| Maintainability | Medium | High | ++ |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Telegram API                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │      bot.py          │  Entry point (~47 lines)
                │  - MCP init          │
                │  - Handler import    │
                │  - Polling start     │
                └──────────┬───────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌───────────┐   ┌──────────┐   ┌──────────────┐
    │ handlers/ │   │  auth/   │   │   storage/   │
    └─────┬─────┘   └────┬─────┘   └──────┬───────┘
          │              │                 │
          │              │                 │
          ▼              ▼                 ▼
    ┌──────────┐   ┌──────────┐     ┌──────────┐
    │   ai/    │◄──┤  models/ │     │   core/  │
    │processor │   └──────────┘     │ telegram │
    └────┬─────┘                    │ openai   │
         │                          │ async    │
         │                          └──────────┘
         ▼
    ┌──────────────┐
    │  OpenAI API  │
    │  MCP Tools   │
    └──────────────┘
```

## Module Breakdown

### 1. Entry Point

#### `bot.py` (47 lines)
- Инициализация MCP manager
- Импорт handlers (автоматическая регистрация через декораторы)
- Запуск polling
- Lambda handler (для webhook режима)

### 2. Core Layer (`core/`)

Базовая инициализация и общие сервисы.

#### `core/telegram.py`
- Создание bot instance
- Настройка логирования
- Экспорт: `bot`, `app_logger`

#### `core/openai_client.py`
- Инициализация OpenAI client
- Экспорт: `client`

#### `core/async_helpers.py`
- Global event loop для async операций
- `run_async()` — запуск async из sync context
- Используется для MCP operations

### 3. Configuration (`config.py`)

Централизованная конфигурация:
- Environment variables (Telegram, OpenAI, S3)
- Constants (rate limits, history length, timeouts)
- Без логики, только данные

### 4. Storage Layer (`storage/`)

Работа с S3-совместимым хранилищем.

#### `storage/s3_client.py`
- `get_s3_client()` — создание S3 client

#### `storage/chat_history.py`
- `get_chat_history(chat_id)` — получить историю
- `save_chat_history(chat_id, history)` — сохранить историю
- `clear_chat_history(chat_id)` — очистить историю

#### `storage/user_settings.py`
- `get_user_settings(chat_id)` — получить настройки
- `save_user_settings(chat_id, settings)` — сохранить настройки
- `get_user_model(chat_id)` — получить выбранную модель
- `set_user_model(chat_id, model)` — установить модель
- `should_use_mcp_for_user(chat_id)` — проверить MCP статус
- `set_mcp_for_user(chat_id, enabled)` — включить/выключить MCP

**S3 структура:**
```
s3://bucket/
  ├── {chat_id}.json              # Chat history
  ├── {chat_id}_settings.json     # User settings (model, mcp_enabled)
  └── {ADMIN_CHAT_ID}_users.json  # Users database
```

### 5. Auth Layer (`auth/`)

Управление доступом и пользователями.

#### `auth/validators.py`
- `validate_username(username)` — валидация Telegram username

#### `auth/user_manager.py`
- `get_users_db()` — получить базу пользователей
- `save_users_db(users_db)` — сохранить базу
- `register_user(username, chat_id)` — регистрация с уведомлением админа
- `get_user_status(username)` — получить статус (pending/approved/denied)
- `set_user_status(username, status)` — установить статус

#### `auth/access_control.py`
- `is_authorized(message)` — проверка доступа к боту
- `is_admin(message)` — проверка админских прав

### 6. Models Layer (`models/`)

Работа с AI моделями.

#### `models/model_manager.py`
- `fetch_models()` — получить список моделей из API
- Группировка по `owned_by`
- Fallback на default список при ошибке

### 7. AI Layer (`ai/`)

Core AI processing logic.

#### `ai/processor.py`
- `process_text_message(text, chat_id, image_content=None)` — main AI function
- Интеграция с OpenAI API
- Vision model support (base64 encoding)
- MCP tool calling loop (max 5 iterations)
- History trimming (max 50 messages)
- Error handling с auto-retry

**Tool Calling Flow:**
1. Get MCP tools if enabled for user
2. Call OpenAI API with tools parameter
3. If `tool_calls` in response:
   - Execute each tool via MCP manager
   - Add results to history
   - Retry API call with results
   - Max 5 iterations to prevent loops
4. Extract final text response
5. Save history to S3

### 8. Handlers Layer (`handlers/`)

Telegram message handlers (используют декораторы).

#### `handlers/commands.py`
User commands:
- `/start`, `/help` — welcome message
- `/models` — list available models
- `/model <name>` — select model
- `/new` — clear chat history
- `/image <prompt>` — generate image via DALL-E 3

#### `handlers/admin_commands.py`
Admin-only commands:
- `/users` — list all users with statuses
- `/approve <username>` — approve user
- `/deny <username>` — deny user
- `/mcpstatus` — MCP servers status

#### `handlers/mcp_commands.py`
MCP management:
- `/tools` — list available MCP tools
- `/mcp on/off` — enable/disable MCP for user
- `/mcp` — show current MCP status

#### `handlers/messages.py`
Main message handler:
- Text messages → `process_text_message()`
- Photo messages → vision model
- Rate limiting (10 req/min)
- Typing indicator
- Long message splitting (>4096 chars)
- HTML parse error fallback

#### `handlers/voice.py`
Voice message handler:
- Whisper transcription
- Text processing via AI
- TTS response (nova voice, opus format)
- Temp file cleanup

### 9. Utils Layer (`utils/`)

Вспомогательные функции.

#### `utils/formatters.py`
- `escape_html(text)` — HTML escaping
- `markdown_to_html(text)` — Markdown → Telegram HTML
- `escape_markdown_v2(text)` — MarkdownV2 escaping

**Поддерживаемый Markdown:**
- `**bold**` → `<b>`
- `*italic*` → `<i>`
- `` `code` `` → `<code>`
- ` ```code block``` ` → `<pre>`
- `[link](url)` → `<a>`
- `~~strikethrough~~` → `<s>`
- `# Header` → bold с emoji

#### `utils/messaging.py`
- `send_long_message()` — автоматическая разбивка длинных сообщений

#### `utils/rate_limiter.py`
- `check_rate_limit(chat_id)` → (allowed: bool, wait_time: int)
- Global `rate_limit_data` dict
- 10 requests per 60 seconds (configurable)

#### `utils/typing_indicator.py`
- `start_typing(chat_id)` — начать typing action
- `stop_typing(chat_id)` — остановить typing
- Background thread, sends every 4 seconds

## Data Flow

### User Message Processing

```
1. User sends message
   ↓
2. handlers/messages.py → echo_message()
   ↓
3. auth/access_control.py → is_authorized()
   ↓
4. utils/rate_limiter.py → check_rate_limit()
   ↓
5. utils/typing_indicator.py → start_typing()
   ↓
6. ai/processor.py → process_text_message()
   ├─ storage/chat_history.py → get_chat_history()
   ├─ storage/user_settings.py → get_user_model()
   ├─ core/async_helpers.py → run_async(mcp_manager.get_tools())
   ├─ core/openai_client.py → client.chat.completions.create()
   ├─ [Tool calls loop if needed]
   └─ storage/chat_history.py → save_chat_history()
   ↓
7. utils/messaging.py → send_long_message()
   ↓
8. utils/typing_indicator.py → stop_typing()
```

### Admin User Approval Flow

```
1. New user sends /start
   ↓
2. auth/access_control.py → is_authorized()
   ↓
3. auth/user_manager.py → register_user()
   ├─ auth/validators.py → validate_username()
   ├─ storage/s3_client.py → get_s3_client()
   ├─ save to S3: {ADMIN_CHAT_ID}_users.json
   └─ core/telegram.py → bot.send_message(ADMIN_CHAT_ID)
   ↓
4. Admin receives notification with /approve and /deny commands
   ↓
5. Admin runs /approve <username>
   ↓
6. handlers/admin_commands.py → approve_user()
   ↓
7. auth/user_manager.py → set_user_status("approved")
   ↓
8. User receives approval notification
```

## Design Patterns

### 1. Singleton Pattern
- `mcp_manager` — global instance, initialized in `bot.py`
- `bot` instance — created once in `core/telegram.py`
- Event loop — created once in `core/async_helpers.py`

### 2. Decorator Pattern
- All handlers use `@bot.message_handler()` decorators
- Automatic registration on import

### 3. Repository Pattern
- `storage/` modules act as repositories for S3 data
- Abstraction над S3 operations

### 4. Facade Pattern
- `ai/processor.py` — facade для complex AI operations
- Скрывает детали OpenAI API, MCP tools, history management

## Error Handling

### BadRequestError (Context Overflow)
```python
try:
    chat_completion = client.chat.completions.create(...)
except BadRequestError:
    clear_chat_history(chat_id)
    return process_text_message(text, chat_id)  # Retry
```

### MCP Graceful Degradation
```python
try:
    tools_param = run_async(mcp_manager.get_all_tools())
except Exception as e:
    app_logger.error(f"MCP failed: {e}")
    tools_param = None  # Continue without tools
```

### HTML Parse Error Fallback
```python
try:
    send_long_message(..., parse_mode="HTML")
except Exception as e:
    if "can't parse entities" in str(e):
        # Send as plain text without formatting
        bot.reply_to(message, ai_response)
```

## Testing Strategy

### Unit Tests (Future)
```python
# Example test structure
tests/
├── test_auth/
│   ├── test_validators.py
│   ├── test_user_manager.py
│   └── test_access_control.py
├── test_storage/
│   ├── test_chat_history.py
│   └── test_user_settings.py
├── test_utils/
│   ├── test_formatters.py
│   └── test_rate_limiter.py
└── test_ai/
    └── test_processor.py
```

### Integration Tests
- Docker Compose с test containers
- MinIO test bucket
- Mock Telegram API
- Mock OpenAI API

## Deployment

### Docker Build Process
1. `Dockerfile` копирует все модули
2. Alpine Linux + Python 3.11
3. Node.js для MCP servers
4. Non-privileged user `botuser`
5. Mounted volumes: `mcp_workspace/`, `mcp.json`

### Rollback Plan
```bash
# Если что-то сломалось
mv bot.py.backup bot.py
rm -rf core/ storage/ auth/ models/ ai/ handlers/ utils/ config.py
docker compose restart bot
```

## Performance Considerations

### Memory Usage
- History limited to 50 messages per chat
- Vision tokens limited to 4000
- Tool call iterations limited to 5

### Rate Limiting
- 10 requests per 60 seconds per user
- Admin bypass
- Wait time calculation

### Async Operations
- MCP calls run in dedicated event loop
- Non-blocking for sync handlers

## Security

### Access Control
- Three-tier system: admin → approved → pending/denied
- Username validation (5-32 chars, alphanumeric + underscore)
- Admin-only commands protected by `is_admin()` check

### Data Privacy
- Chat history stored per user (isolated)
- S3 credentials in environment variables (not in code)
- Docker secrets support via env files

### Input Validation
- Username validation before registration
- Model name validation against fetched list
- Rate limiting to prevent abuse

## Future Improvements

### Code Quality
- [ ] Add type hints everywhere
- [ ] Add docstrings to all public functions
- [ ] Implement unit tests (pytest)
- [ ] Add integration tests

### Features
- [ ] Webhook mode support (alternative to polling)
- [ ] Multiple admin support
- [ ] User usage statistics
- [ ] Model cost tracking
- [ ] Conversation export

### Performance
- [ ] Redis cache for user settings
- [ ] Async storage operations
- [ ] Connection pooling for S3

### Monitoring
- [ ] Prometheus metrics
- [ ] Health check endpoint
- [ ] Error tracking (Sentry)
- [ ] Usage analytics

## Contributing

При добавлении новых features:

1. **Новая команда** → добавить в `handlers/commands.py` или создать новый handler
2. **Новое хранилище** → добавить функции в `storage/`
3. **Новая AI функция** → расширить `ai/processor.py`
4. **Новая утилита** → добавить в `utils/`

Следуйте принципу **Single Responsibility** — каждый модуль отвечает только за одну область.

## References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenAI API](https://platform.openai.com/docs/api-reference)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MinIO Python SDK](https://min.io/docs/minio/linux/developers/python/minio-py.html)
