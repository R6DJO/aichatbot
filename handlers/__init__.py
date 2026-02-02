"""
Handlers initialization.
All handlers are registered via decorators in their respective modules.
"""

# Import all handler modules to register their decorators
from handlers import commands
from handlers import admin_commands
from handlers import mcp_commands
from handlers import messages
from handlers import voice
