"""
Simplified MCP Server Manager with better async handling
"""

import asyncio
import logging
import os
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure MCP logger (stdout only for Docker)
# Note: logging.basicConfig() in core.telegram already configures root logger
# so we just get the logger without adding extra handlers (to avoid duplicate logs)
mcp_logger = logging.getLogger("mcp")
mcp_logger.setLevel(logging.INFO)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server"""
    name: str
    transport: str  # "stdio" or "sse"
    command: str  # for stdio (e.g., "npx")
    args: List[str]  # for stdio
    url: Optional[str] = None  # for sse
    env: Optional[Dict[str, str]] = None
    enabled: bool = True


class _ServerConnection:
    """
    Manages a persistent connection to a single MCP server.

    All context manager operations (stdio_client, ClientSession) run
    inside a single dedicated asyncio Task, so anyio cancel scopes are
    always entered and exited within the same task — avoiding the
    "Attempted to exit cancel scope in a different task" error.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._ready: asyncio.Event = asyncio.Event()
        self._start_error: Optional[Exception] = None
        self._stopped = False

    async def start(self):
        """Launch the background task and wait until the session is ready."""
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.config.name}")
        await self._ready.wait()
        if self._start_error:
            raise self._start_error

    async def _run(self):
        """Background task: owns the connection lifecycle."""
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
        )
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    mcp_logger.info(f"Connected to {self.config.name}")
                    self._ready.set()

                    while True:
                        item = await self._queue.get()
                        if item is None:  # shutdown signal
                            break
                        future, method, args, kwargs = item
                        try:
                            result = await getattr(session, method)(*args, **kwargs)
                            future.set_result(result)
                        except Exception as exc:
                            future.set_exception(exc)

        except Exception as exc:
            mcp_logger.error(f"Connection to {self.config.name} failed: {exc}")
            self._start_error = exc
            self._ready.set()  # unblock start() callers
        finally:
            self._stopped = True
            # Drain remaining requests with an error
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None:
                    future = item[0]
                    if not future.done():
                        future.set_exception(
                            RuntimeError(f"MCP server {self.config.name} disconnected")
                        )

    async def call(self, method: str, *args, **kwargs) -> Any:
        """Send a method call to the background task and await the result."""
        if self._stopped:
            raise RuntimeError(f"MCP server {self.config.name} is not running")
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put((future, method, args, kwargs))
        return await future

    async def stop(self):
        """Gracefully shut down the background task."""
        if self._task and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()
            mcp_logger.info(f"Closed session for {self.config.name}")


class MCPServerManager:
    """MCP server manager with connection pooling for better performance"""

    def __init__(self, server_configs: List[MCPServerConfig], cache_ttl: int = None):
        self.configs = [c for c in server_configs if c.enabled]
        self._tool_cache = {}  # {tool_name: server_name}
        self._tools_list_cache = []  # Cached list of OpenAI-formatted tools
        self._cache_timestamp = 0

        # Per-server persistent connections
        self._connections: Dict[str, _ServerConnection] = {}

        # Use provided TTL or default from environment/config
        if cache_ttl is None:
            try:
                from config import MCP_CACHE_TTL_SECONDS
                cache_ttl = MCP_CACHE_TTL_SECONDS
            except ImportError:
                cache_ttl = 3600  # Fallback to 1 hour

        self._cache_ttl = cache_ttl
        self._session_ttl = 3600  # kept for API compatibility
        mcp_logger.info(
            f"MCPServerManager initialized with {len(self.configs)} configs, "
            f"cache TTL={self._cache_ttl}s"
        )

    # ------------------------------------------------------------------
    # Internal connection helpers
    # ------------------------------------------------------------------

    async def _get_or_create_connection(self, config: MCPServerConfig) -> _ServerConnection:
        """Return a running _ServerConnection, creating one if needed."""
        conn = self._connections.get(config.name)
        if conn and not conn._stopped:
            return conn

        # Remove stale entry if present
        if config.name in self._connections:
            del self._connections[config.name]

        mcp_logger.info(f"Connecting to {config.name}...")
        conn = _ServerConnection(config)
        await conn.start()
        self._connections[config.name] = conn
        return conn

    async def _close_connection(self, server_name: str):
        """Stop and remove a connection."""
        conn = self._connections.pop(server_name, None)
        if conn:
            await conn.stop()

    async def close_all_sessions(self):
        """Close all active sessions (call on shutdown)"""
        for name in list(self._connections.keys()):
            await self._close_connection(name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def connect_to_server(self, config: MCPServerConfig):
        """Context manager for connecting to a single server (backwards compatibility)"""
        if config.transport != "stdio":
            raise NotImplementedError("Only stdio transport is supported")

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env,
        )

        mcp_logger.info(f"Connecting to {config.name}...")

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mcp_logger.info(f"Connected to {config.name}")
                yield session

    async def get_all_tools(self) -> List[Dict]:
        """Get tools from all configured servers and update cache"""
        import time

        if self._is_cache_valid() and self._tools_list_cache:
            mcp_logger.info(f"Using cached tools: {len(self._tools_list_cache)} tools")
            return self._tools_list_cache

        all_tools = []
        mcp_logger.info("Fetching fresh tools from all servers...")

        for config in self.configs:
            try:
                conn = await self._get_or_create_connection(config)
                tools_result = await conn.call("list_tools")

                for tool in tools_result.tools:
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "No description available",
                            "parameters": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                        },
                        "_mcp_server": config.name,
                    }
                    all_tools.append(openai_tool)
                    self._tool_cache[tool.name] = config.name

                mcp_logger.info(f"Got {len(tools_result.tools)} tools from {config.name}")

            except Exception as e:
                mcp_logger.error(f"Failed to get tools from {config.name}: {e}")
                await self._close_connection(config.name)

        self._cache_timestamp = time.time()
        self._tools_list_cache = all_tools
        mcp_logger.info(f"Tool cache updated with {len(self._tool_cache)} tools")
        return all_tools

    def _is_cache_valid(self) -> bool:
        import time
        if not self._tool_cache:
            return False
        return (time.time() - self._cache_timestamp) < self._cache_ttl

    async def execute_tool(self, tool_name: str, arguments: Dict) -> Any:
        """Execute a tool by finding which server has it and connecting"""
        import time
        start_time = time.time()

        config = self._get_config_from_cache(tool_name)
        if config is None:
            config = await self._find_server_with_tool(tool_name)

        if config is None:
            raise Exception(f"Tool '{tool_name}' not found in any connected server")

        return await self._execute_tool_on_server(config, tool_name, arguments, start_time)

    def _get_config_from_cache(self, tool_name: str) -> Optional[MCPServerConfig]:
        if not self._is_cache_valid() or tool_name not in self._tool_cache:
            return None

        server_name = self._tool_cache[tool_name]
        mcp_logger.info(f"Using cached server '{server_name}' for tool '{tool_name}'")

        config = next((c for c in self.configs if c.name == server_name), None)
        if config is None:
            mcp_logger.warning(f"Cached server '{server_name}' not found in configs, cache invalidated")
            self._tool_cache.pop(tool_name, None)
        return config

    async def _find_server_with_tool(self, tool_name: str) -> Optional[MCPServerConfig]:
        mcp_logger.info(f"Cache miss for tool '{tool_name}', searching all servers")

        for config in self.configs:
            try:
                conn = await self._get_or_create_connection(config)
                tools_result = await conn.call("list_tools")
                if any(tool.name == tool_name for tool in tools_result.tools):
                    self._tool_cache[tool_name] = config.name
                    return config
            except Exception as e:
                mcp_logger.exception(f"Error checking {config.name} for tool {tool_name}: {e}")
                await self._close_connection(config.name)

        return None

    async def _execute_tool_on_server(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: Dict,
        start_time: float,
    ) -> Any:
        from config import MCP_TOOL_TIMEOUT_SECONDS
        import time

        try:
            conn = await self._get_or_create_connection(config)

            mcp_logger.info(
                f"Executing {tool_name} on {config.name}, "
                f"args={json.dumps(arguments, ensure_ascii=False)[:200]}"
            )

            result = await asyncio.wait_for(
                conn.call("call_tool", tool_name, arguments),
                timeout=MCP_TOOL_TIMEOUT_SECONDS,
            )

            duration = time.time() - start_time
            mcp_logger.info(
                f"Tool executed: {tool_name}, duration={duration:.2f}s, "
                f"result_size={len(str(result))} chars"
            )

            return self._extract_result_content(result)

        except asyncio.TimeoutError:
            error_msg = f"Tool '{tool_name}' execution timed out after {MCP_TOOL_TIMEOUT_SECONDS} seconds"
            mcp_logger.error(error_msg)
            await self._close_connection(config.name)
            raise Exception(error_msg)
        except Exception as e:
            mcp_logger.exception(f"Error executing tool {tool_name} on {config.name}: {e}")
            await self._close_connection(config.name)
            self._tool_cache.pop(tool_name, None)
            raise

    def _extract_result_content(self, result: Any) -> str:
        if hasattr(result, "content") and result.content:
            if len(result.content) > 0:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    return content_item.text
                return str(content_item)
            return str(result.content)
        return str(result)

    def get_server_status(self) -> Dict[str, str]:
        status = {}
        for config in self.configs:
            status[config.name] = "configured" if config.enabled else "disabled"
        return status

    def is_configured(self) -> bool:
        return len(self.configs) > 0


def load_mcp_configs_from_json(config_file: str = "mcp.json") -> List[MCPServerConfig]:
    """Parse MCP server configurations from JSON file"""
    configs = []

    if not os.path.exists(config_file):
        mcp_logger.warning(f"MCP config file '{config_file}' not found, no servers will be loaded")
        return configs

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        mcp_servers = config_data.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            if not server_config.get("enabled", True):
                mcp_logger.info(f"Skipping disabled server: {server_name}")
                continue

            command = server_config.get("command", "npx")
            args = server_config.get("args", [])
            env = server_config.get("env", None)

            configs.append(MCPServerConfig(
                name=server_name,
                transport="stdio",
                command=command,
                args=args,
                env=env,
                enabled=True,
            ))
            mcp_logger.info(f"Loaded {server_name} server: command={command}, args={args}")

        mcp_logger.info(f"Loaded {len(configs)} MCP server configurations from {config_file}")

    except json.JSONDecodeError as e:
        mcp_logger.error(f"Error parsing MCP config file: {e}")
    except Exception as e:
        mcp_logger.error(f"Error loading MCP config: {e}")

    return configs
