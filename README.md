# Telegram AI Chat Bot

Production-ready Telegram bot with multi-modal AI capabilities, MCP tools integration, and advanced performance optimizations.

## Features

- 💬 **Multi-Model Text Chat** — Support for GLM, GPT, Qwen, and other OpenAI-compatible models
- 👁️ **Image Analysis** — GPT-4 Vision for understanding images
- 🎨 **Image Generation** — DALL-E 3 integration
- 🎤 **Voice Messages** — Whisper transcription + TTS responses
- 🔧 **MCP Tools** — External tool integration (filesystem, web search, GitHub, databases)
- 💾 **S3 Storage** — Persistent chat history and settings in S3-compatible storage
- 🔐 **Admin Approval System** — User access control with pending/approved/denied statuses
- ⚡ **Performance Optimized** — Connection pooling, caching, detailed timing logs
- 📊 **Production Ready** — Comprehensive logging, graceful shutdown, error handling
- 🏗️ **Modular Architecture** — 19 modules across 7 packages

## Quick Start

### Prerequisites

- Python 3.10+
- Docker and Docker Compose
- Telegram Bot Token ([create one](https://t.me/BotFather))
- OpenAI API key or compatible API endpoint

### Installation

```bash
# 1. Clone and setup environment
git clone https://github.com/R6DJO/aichatbot
cd aichatbot
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 3. Setup MCP (optional but recommended)
cp mcp.json.example mcp.json
# Edit mcp.json to enable desired tools

# 4. Start services
docker compose up -d

# 5. Check logs
docker compose logs -f bot
```

### Configuration

Required environment variables in `.env`:

```bash
# Telegram Bot
TG_BOT_TOKEN=your_telegram_bot_token

# Administrator
ADMIN_USERNAME=YourUsername
ADMIN_CHAT_ID=123456789  # Get from @userinfobot

# OpenAI API
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=http://localhost:8317/v1

# S3 Storage
S3_KEY_ID=botuser
S3_KEY_SECRET=botpassword123
S3_BUCKET=aichatbot
MINIO_ENDPOINT=http://minio:9000  # or other S3-compatible endpoint

# MCP (optional)
MCP_ENABLED=true
MCP_WARMUP_CACHE=true
MCP_CACHE_TTL_SECONDS=3600  # 1 hour
```

See `.env.example` for full configuration options.

## Bot Commands

### User Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Welcome message and help |
| `/models` | List available AI models |
| `/model <name>` | Select AI model for chat |
| `/new` | Clear chat history |
| `/image <prompt>` | Generate image with DALL-E 3 |
| `/tools` | List available MCP tools |
| `/mcp on\|off` | Enable/disable MCP tools |
| `/mcp` | Show MCP status |

### Admin Commands

| Command | Description |
|---------|-------------|
| `/users` | List all users with statuses |
| `/approve <username>` | Approve user access |
| `/deny <username>` | Deny user access |
| `/mcpstatus` | Check MCP servers status |

## MCP Tools Integration

The bot supports external tools via Model Context Protocol (MCP):

### Available Tools

- **🔍 Web Search** — Brave Search for internet queries
- **📁 Filesystem** — Read/write files in workspace
- **🐙 GitHub** — Repository operations, issues, PRs
- **🗄️ Databases** — PostgreSQL, SQLite queries
- **🌐 HTTP** — API requests and webhooks

### Example Interaction

```
You: Search for latest Python news
Bot: [Uses brave-search MCP tool]
     Here's what I found:
     1. Python 3.13 released with...
     2. New features in...

You: Save summary to notes.txt
Bot: [Uses filesystem MCP tool]
     ✅ Saved to mcp_workspace/notes.txt
```

Configuration: See `docs/MCP_SETUP.md`

## Performance Features

### Connection Pooling ⚡

- **MCP sessions** are reused for 1 hour (configurable)
- **~100ms faster** per tool call after first use
- **Automatic cleanup** on errors and shutdown

### API Request Monitoring 📊

All OpenAI API calls are logged with timing:

```log
API request started: chat_id=123, model=glm-4.7, messages=5, tools=4
API response received: chat_id=123, model=glm-4.7, duration=2.34s
Tool executed: brave_web_search, duration=1.40s
```

Enables:
- Performance debugging
- Bottleneck identification
- Cost monitoring

See `docs/PERFORMANCE.md` for details.

## Architecture

### Modular Structure

```
bot.py (47 lines) → Entry point
├── core/           → Telegram, OpenAI, async helpers
├── config/         → Environment variables and constants
├── handlers/       → Command and message handlers
├── auth/           → User management and access control
├── ai/             → AI processing and tool execution
├── storage/        → S3 operations (history, settings)
├── models/         → Model management
├── utils/          → Formatters, rate limiter, typing indicator
└── mcp_manager.py  → MCP server connection pooling
```

### Request Flow

```
User → Telegram → auth/ → ai/processor.py
                             ↓
                        OpenAI API
                             ↓
                        MCP Tools (pooled connections)
                             ↓
                        S3 Storage
```

See `docs/ARCHITECTURE.md` for detailed documentation.

## Deployment

### Docker (Recommended)

```bash
docker compose up -d
```

Services:
- **bot** — Telegram bot with MCP support
- **minio** — S3-compatible storage
- **minio-setup** — Automatic bucket and user creation

### Manual

```bash
# Start MinIO
docker compose up -d minio minio-setup

# Run bot locally
source venv/bin/activate
python bot.py
```

### Production Considerations

1. **Environment**: Use production `.env` with secure credentials
2. **Storage**: Configure AWS S3 or production MinIO cluster
3. **Logging**: Logs go to stdout (Docker best practice)
4. **Monitoring**: Check `docker logs` or container orchestration logs
5. **Scaling**: Single-process design (for multi-worker, use Redis for rate limiter)

## Authorization System

1. **New user** sends message → `pending` status
2. **Admin** receives notification
3. **Admin** approves/denies via `/approve` or `/deny`
4. **User** notified of decision

Statuses:
- ⏳ **Pending** — Waiting for admin approval
- ✅ **Approved** — Access granted
- ❌ **Denied** — Access denied

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot not responding | Check `/users` — are you pending approval? |
| MCP tools not working | Verify `mcp.json` and check `/mcpstatus` |
| S3 connection error | Check `MINIO_ENDPOINT` and credentials |
| Models not loading | Verify `OPENAI_BASE_URL/models` endpoint |
| Docker won't start | Check `docker compose logs minio` and `bot` |
| Permission denied | Ask admin to `/approve <username>` |

## Documentation

- **📖 [Architecture](docs/ARCHITECTURE.md)** — Detailed system design
- **🔧 [MCP Setup](docs/MCP_SETUP.md)** — Tool configuration guide
- **🗄️ [MinIO Setup](docs/MINIO_SETUP.md)** — S3 storage configuration
- **⚡ [Performance](docs/PERFORMANCE.md)** — Optimization details and benchmarks

## Development

### Project Structure

```
aichatbot/
├── bot.py                    # Entry point (47 lines)
├── config/                   # Configuration package
│   └── __init__.py
├── core/                     # Initialization
│   ├── telegram.py
│   ├── openai_client.py
│   └── async_helpers.py
├── handlers/                 # Telegram handlers
│   ├── commands.py
│   ├── admin_commands.py
│   ├── mcp_commands.py
│   ├── messages.py
│   └── voice.py
├── auth/                     # Access control
│   ├── validators.py
│   ├── user_manager.py
│   └── access_control.py
├── ai/                       # AI processing
│   ├── processor.py
│   └── tool_executor.py
├── storage/                  # S3 operations
│   ├── s3_client.py
│   ├── chat_history.py
│   └── user_settings.py
├── models/                   # Model management
│   └── model_manager.py
├── utils/                    # Utilities
│   ├── formatters.py
│   ├── messaging.py
│   ├── rate_limiter.py
│   └── typing_indicator.py
├── mcp_manager.py            # MCP connection pooling
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── mcp.json.example
└── docs/                     # Documentation
    ├── ARCHITECTURE.md
    ├── MCP_SETUP.md
    ├── MINIO_SETUP.md
    └── PERFORMANCE.md
```

### Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run bot in development mode
python bot.py

# Check logs
tail -f logs/bot.log  # if logging to file
docker compose logs -f bot  # if running in Docker
```

### Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Make changes following existing code structure
4. Test thoroughly
5. Submit pull request

## License

This project is licensed under the Business Source License 1.1 (BUSL-1.1).

See [LICENSE](LICENSE) for the full license text.

**Key points:**
- Free to use for any purpose, including commercial use
- Source code available and modifiable
- After Change Date (2028-02-03), converts to GPL v3.0 or later

## Support

- **Issues**: [GitHub Issues](https://github.com/R6DJO/aichatbot/issues)
- **Documentation**: See `docs/` directory
- **Admin**: Contact bot administrator for access

---

**Built with:** Python, pyTelegramBotAPI, OpenAI API, MCP, Docker, MinIO
