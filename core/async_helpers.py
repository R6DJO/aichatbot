"""
Async helpers for running async operations from sync context.
"""

import asyncio
import threading
from core.telegram import app_logger

# Global event loop for async operations
_async_loop = None
_loop_thread = None


def get_or_create_event_loop():
    """Get or create a global event loop for async operations (thread-safe)"""
    global _async_loop, _loop_thread

    if _async_loop is None or not _async_loop.is_running():
        def run_loop(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _async_loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=run_loop, args=(_async_loop,), daemon=True)
        _loop_thread.start()
        app_logger.info("Created global event loop for async operations")

    return _async_loop


def run_async(coro):
    """Run async coroutine in global event loop from sync context"""
    loop = get_or_create_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
