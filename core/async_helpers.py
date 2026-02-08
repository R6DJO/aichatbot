"""
Async helpers - DEPRECATED

This module is deprecated after migration to AsyncTeleBot.
All code is now natively async and doesn't need sync/async bridge.

Keeping this file for backward compatibility only.
"""

import asyncio
import warnings
from core.telegram import app_logger


def run_async(coro):
    """
    DEPRECATED: Run async coroutine from sync context.

    This function is deprecated after migration to AsyncTeleBot.
    All handlers are now async and should use `await` directly.

    Only kept for backward compatibility.
    """
    warnings.warn(
        "run_async() is deprecated. Use async/await directly.",
        DeprecationWarning,
        stacklevel=2
    )
    app_logger.warning("run_async() is deprecated and should not be used")

    return asyncio.run(coro)
