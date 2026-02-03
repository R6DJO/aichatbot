#!/usr/bin/env python3
"""
Telegram AI Chat Bot - Entry Point
Refactored modular architecture.
"""

import os
import json
import signal
import telebot
from core.telegram import bot, app_logger
import handlers  # Import to register all handlers
import ai.processor

# Initialize MCP Manager (global singleton)
if os.environ.get("MCP_ENABLED", "false").lower() == "true":
    try:
        from mcp_manager import MCPServerManager, load_mcp_configs_from_env
        from core.async_helpers import run_async

        configs = load_mcp_configs_from_env()
        ai.processor.mcp_manager = MCPServerManager(configs)
        app_logger.info(f"MCP Manager initialized with {len(configs)} server configs")

        # Warm up cache at startup (optional, can be disabled with MCP_WARMUP_CACHE=false)
        if os.environ.get("MCP_WARMUP_CACHE", "true").lower() == "true":
            try:
                app_logger.info("Warming up MCP tools cache...")
                tools = run_async(ai.processor.mcp_manager.get_all_tools())
                app_logger.info(f"Cache warmed up with {len(tools)} tools")
            except Exception as warmup_error:
                app_logger.warning(f"Failed to warm up cache (will retry on first request): {warmup_error}")
    except Exception as e:
        app_logger.error(f"Failed to initialize MCP Manager: {e}")
        ai.processor.mcp_manager = None
else:
    ai.processor.mcp_manager = None


# AWS Lambda handler для webhook-режима (опционально)
def handler(event, context):
    """AWS Lambda handler для webhook-режима"""
    message = json.loads(event["body"])
    update = telebot.types.Update.de_json(message)

    if update.message is not None:
        try:
            bot.process_new_updates([update])
        except Exception as e:
            app_logger.error(f"Lambda handler error: {e}")

    return {"statusCode": 200, "body": "ok"}


# Graceful shutdown handler
def shutdown_handler(signum, frame):
    """Handle shutdown signals and cleanup resources"""
    app_logger.info(f"Received shutdown signal {signum}, cleaning up...")

    # Close all MCP sessions
    if ai.processor.mcp_manager is not None:
        try:
            from core.async_helpers import run_async
            run_async(ai.processor.mcp_manager.close_all_sessions())
            app_logger.info("All MCP sessions closed")
        except Exception as e:
            app_logger.error(f"Error closing MCP sessions: {e}")

    app_logger.info("Shutdown complete")
    exit(0)


# Запуск бота в режиме polling
if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    app_logger.info("Бот запущен в режиме polling...")
    bot.infinity_polling()
