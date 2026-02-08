#!/usr/bin/env python3
"""
Telegram AI Chat Bot - Entry Point
Async architecture for concurrent request handling.
"""

import os
import signal
import asyncio
from core.telegram import bot, app_logger
import handlers  # Import to register all handlers
import ai.processor

# Global flag for graceful shutdown
shutdown_requested = False

# Initialize MCP Manager (global singleton)
# Note: warmup is done inside async main() to avoid event loop conflicts
if os.environ.get("MCP_ENABLED", "false").lower() == "true":
    try:
        from mcp_manager import MCPServerManager, load_mcp_configs_from_env

        configs = load_mcp_configs_from_env()
        ai.processor.mcp_manager = MCPServerManager(configs)
        app_logger.info(f"MCP Manager initialized with {len(configs)} server configs")
    except Exception as e:
        app_logger.error(f"Failed to initialize MCP Manager: {e}")
        ai.processor.mcp_manager = None
else:
    ai.processor.mcp_manager = None


# Graceful shutdown handler
async def shutdown_handler_async():
    """Handle shutdown and cleanup resources"""
    global shutdown_requested

    if shutdown_requested:
        return  # Already shutting down

    shutdown_requested = True
    app_logger.info("Initiating graceful shutdown...")

    # Stop bot polling
    try:
        await bot.close_session()
        app_logger.info("Bot polling stopped")
    except Exception as e:
        app_logger.warning(f"Error stopping bot: {e}")

    # Close all MCP sessions
    if ai.processor.mcp_manager is not None:
        try:
            await ai.processor.mcp_manager.close_all_sessions()
            app_logger.info("All MCP sessions closed")
        except Exception as e:
            app_logger.error(f"Error closing MCP sessions: {e}")

    app_logger.info("Shutdown complete")


def shutdown_handler(signum, frame):
    """Signal handler for SIGINT/SIGTERM"""
    app_logger.info(f"Received shutdown signal {signum}")

    # Get the current event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create a new one for cleanup
        app_logger.warning("No running event loop found, creating new one for cleanup")
        asyncio.run(shutdown_handler_async())
        exit(0)
        return

    # Schedule shutdown in the current event loop
    loop.create_task(shutdown_handler_async())

    # Give some time for cleanup before forcing exit
    loop.call_later(5.0, lambda: exit(0))


# Запуск бота в режиме async polling
async def main():
    """Main entry point"""
    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Warm up MCP cache inside the main event loop (avoids async generator errors)
    if ai.processor.mcp_manager and os.environ.get("MCP_WARMUP_CACHE", "true").lower() == "true":
        try:
            app_logger.info("Warming up MCP tools cache...")
            tools = await ai.processor.mcp_manager.get_all_tools()
            app_logger.info(f"Cache warmed up with {len(tools)} tools")
        except Exception as warmup_error:
            app_logger.warning(f"Failed to warm up cache (will retry on first request): {warmup_error}")

    app_logger.info("Бот запущен в async режиме polling...")
    await bot.infinity_polling()


if __name__ == "__main__":
    asyncio.run(main())
