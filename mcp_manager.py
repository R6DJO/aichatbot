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


class MCPServerManager:
    """MCP server manager with connection pooling for better performance"""

    def __init__(self, server_configs: List[MCPServerConfig], cache_ttl: int = None):
        self.configs = [c for c in server_configs if c.enabled]
        self._tool_cache = {}  # {tool_name: server_name}
        self._tools_list_cache = []  # Cached list of OpenAI-formatted tools
        self._cache_timestamp = 0

        # Connection pooling
        self._active_sessions = {}  # {server_name: (session, streams_context, last_used_timestamp)}
        self._session_ttl = 300  # 5 minutes by default

        # Use provided TTL or default from environment/config
        if cache_ttl is None:
            try:
                from config import MCP_CACHE_TTL_SECONDS
                cache_ttl = MCP_CACHE_TTL_SECONDS
            except ImportError:
                cache_ttl = 300  # Fallback to 5 minutes

        self._cache_ttl = cache_ttl
        mcp_logger.info(f"MCPServerManager initialized with {len(self.configs)} configs, cache TTL={self._cache_ttl}s, session TTL={self._session_ttl}s")

    async def _get_or_create_session(self, config: MCPServerConfig):
        """Get existing session or create a new one"""
        import time

        # Check if we have an active session
        if config.name in self._active_sessions:
            session_data = self._active_sessions[config.name]
            session = session_data['session']
            last_used = session_data['last_used']

            # Check if session is still valid (not expired)
            if (time.time() - last_used) < self._session_ttl:
                # Update last used time
                session_data['last_used'] = time.time()
                mcp_logger.info(f"Reusing existing session for {config.name}")
                return session
            else:
                # Session expired, close it
                mcp_logger.info(f"Session for {config.name} expired, creating new one")
                await self._close_session(config.name)

        # Create new session
        if config.transport != "stdio":
            raise NotImplementedError("Only stdio transport is supported")

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env
        )

        mcp_logger.info(f"Connecting to {config.name}...")

        # Create stdio_client context manager
        stdio_ctx = stdio_client(server_params)
        read_stream, write_stream = await stdio_ctx.__aenter__()

        # Create session context manager
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        await session.initialize()

        # Store session with all necessary context managers for proper cleanup
        self._active_sessions[config.name] = {
            'session': session,
            'session_ctx': session_ctx,
            'stdio_ctx': stdio_ctx,
            'last_used': time.time()
        }
        mcp_logger.info(f"Connected to {config.name}")

        return session

    async def _close_session(self, server_name: str):
        """Close an active session"""
        if server_name in self._active_sessions:
            session_data = self._active_sessions[server_name]
            try:
                # Close session first
                await session_data['session_ctx'].__aexit__(None, None, None)
                # Then close stdio streams
                await session_data['stdio_ctx'].__aexit__(None, None, None)
                mcp_logger.info(f"Closed session for {server_name}")
            except Exception as e:
                mcp_logger.error(f"Error closing session for {server_name}: {e}")
            finally:
                del self._active_sessions[server_name]

    async def close_all_sessions(self):
        """Close all active sessions (call on shutdown)"""
        for server_name in list(self._active_sessions.keys()):
            await self._close_session(server_name)

    @asynccontextmanager
    async def connect_to_server(self, config: MCPServerConfig):
        """Context manager for connecting to a single server (backwards compatibility)"""
        if config.transport != "stdio":
            raise NotImplementedError("Only stdio transport is supported")

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env
        )

        mcp_logger.info(f"Connecting to {config.name}...")

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mcp_logger.info(f"Connected to {config.name}")
                yield session

    async def get_all_tools(self) -> List[Dict]:
        """Get tools from all configured servers and update cache"""
        # Return cached tools if still valid
        if self._is_cache_valid() and self._tools_list_cache:
            mcp_logger.info(f"Using cached tools: {len(self._tools_list_cache)} tools")
            return self._tools_list_cache

        all_tools = []
        import time

        mcp_logger.info("Fetching fresh tools from all servers...")
        for config in self.configs:
            try:
                # Use connection pooling instead of context manager
                session = await self._get_or_create_session(config)
                tools_result = await session.list_tools()

                for tool in tools_result.tools:
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "No description available",
                            "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                        },
                        "_mcp_server": config.name
                    }
                    all_tools.append(openai_tool)

                    # Update cache: tool_name -> server_name
                    self._tool_cache[tool.name] = config.name

                mcp_logger.info(f"Got {len(tools_result.tools)} tools from {config.name}")
            except Exception as e:
                mcp_logger.error(f"Failed to get tools from {config.name}: {e}")
                # Close session on error
                await self._close_session(config.name)

        # Update cache timestamp and tools list
        self._cache_timestamp = time.time()
        self._tools_list_cache = all_tools
        mcp_logger.info(f"Tool cache updated with {len(self._tool_cache)} tools")

        return all_tools

    def _is_cache_valid(self) -> bool:
        """Check if tool cache is still valid"""
        import time
        if not self._tool_cache:
            return False
        return (time.time() - self._cache_timestamp) < self._cache_ttl

    async def execute_tool(self, tool_name: str, arguments: Dict) -> Any:
        """Execute a tool by finding which server has it and connecting"""
        import time
        start_time = time.time()

        # Try cache first
        config = self._get_config_from_cache(tool_name)

        # If cache miss or failed, search all servers
        if config is None:
            config = await self._find_server_with_tool(tool_name)

        if config is None:
            raise Exception(f"Tool '{tool_name}' not found in any connected server")

        # Execute tool (single code path - eliminates duplication)
        return await self._execute_tool_on_server(config, tool_name, arguments, start_time)

    def _get_config_from_cache(self, tool_name: str) -> Optional[MCPServerConfig]:
        """Try to get server config from cache"""
        if not self._is_cache_valid() or tool_name not in self._tool_cache:
            return None

        server_name = self._tool_cache[tool_name]
        mcp_logger.info(f"Using cached server '{server_name}' for tool '{tool_name}'")

        # Find config by name
        config = next((c for c in self.configs if c.name == server_name), None)

        # Validate config still exists
        if config is None:
            mcp_logger.warning(f"Cached server '{server_name}' not found in configs, cache invalidated")
            self._tool_cache.pop(tool_name, None)

        return config

    async def _find_server_with_tool(self, tool_name: str) -> Optional[MCPServerConfig]:
        """Search all servers for a tool using connection pooling"""
        mcp_logger.info(f"Cache miss for tool '{tool_name}', searching all servers")

        for config in self.configs:
            try:
                # Use connection pooling
                session = await self._get_or_create_session(config)

                # List tools to see if this server has the requested tool
                tools_result = await session.list_tools()
                has_tool = any(tool.name == tool_name for tool in tools_result.tools)

                if has_tool:
                    # Update cache
                    self._tool_cache[tool_name] = config.name
                    return config

            except Exception as e:
                # Use exception() to log full traceback
                mcp_logger.exception(f"Error checking {config.name} for tool {tool_name}: {e}")
                # Close session on error
                await self._close_session(config.name)
                continue

        return None

    async def _execute_tool_on_server(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: Dict,
        start_time: float
    ) -> Any:
        """Execute tool on a specific server using connection pooling"""
        from config import MCP_TOOL_TIMEOUT_SECONDS
        import time

        try:
            # Use connection pooling - reuse existing session
            session = await self._get_or_create_session(config)

            mcp_logger.info(
                f"Executing {tool_name} on {config.name}, "
                f"args={json.dumps(arguments)[:200]}"
            )

            # Execute the tool with timeout
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=MCP_TOOL_TIMEOUT_SECONDS
            )

            duration = time.time() - start_time
            result_str = str(result)
            mcp_logger.info(
                f"Tool executed: {tool_name}, duration={duration:.2f}s, "
                f"result_size={len(result_str)} chars"
            )

            # Extract content from result
            return self._extract_result_content(result)

        except asyncio.TimeoutError:
            error_msg = f"Tool '{tool_name}' execution timed out after {MCP_TOOL_TIMEOUT_SECONDS} seconds"
            mcp_logger.error(error_msg)
            # Close session on timeout
            await self._close_session(config.name)
            raise Exception(error_msg)
        except Exception as e:
            # Use exception() to log full traceback
            mcp_logger.exception(f"Error executing tool {tool_name} on {config.name}: {e}")
            # Close session on error and invalidate cache
            await self._close_session(config.name)
            self._tool_cache.pop(tool_name, None)
            raise

    def _extract_result_content(self, result: Any) -> str:
        """Extract text content from MCP result"""
        if hasattr(result, 'content') and result.content:
            if len(result.content) > 0:
                content_item = result.content[0]
                if hasattr(content_item, 'text'):
                    return content_item.text
                return str(content_item)
            return str(result.content)
        return str(result)

    def get_server_status(self) -> Dict[str, str]:
        """Get status of all configured servers"""
        status = {}
        for config in self.configs:
            status[config.name] = "configured" if config.enabled else "disabled"
        return status

    def is_configured(self) -> bool:
        """Check if any servers are configured"""
        return len(self.configs) > 0


def load_mcp_configs_from_json(config_file: str = "mcp.json") -> List[MCPServerConfig]:
    """Parse MCP server configurations from JSON file"""
    configs = []

    # Check if config file exists
    if not os.path.exists(config_file):
        mcp_logger.warning(f"MCP config file '{config_file}' not found, no servers will be loaded")
        return configs

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        mcp_servers = config_data.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            # Skip disabled servers
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
                enabled=True
            ))

            mcp_logger.info(f"Loaded {server_name} server: command={command}, args={args}")

        mcp_logger.info(f"Loaded {len(configs)} MCP server configurations from {config_file}")

    except json.JSONDecodeError as e:
        mcp_logger.error(f"Error parsing MCP config file: {e}")
    except Exception as e:
        mcp_logger.error(f"Error loading MCP config: {e}")

    return configs


def load_mcp_configs_from_env() -> List[MCPServerConfig]:
    """DEPRECATED: Use load_mcp_configs_from_json() instead

    This function is kept for backwards compatibility.
    It will try to load from mcp.json first, then fall back to environment variables.
    """
    # Try JSON first
    configs = load_mcp_configs_from_json()
    if configs:
        return configs

    # Fall back to environment variables (old method)
    mcp_logger.warning("No mcp.json found, falling back to environment variables (deprecated)")
    configs = []

    # Filesystem server
    if os.environ.get("MCP_FILESYSTEM_ENABLED", "false").lower() == "true":
        command = os.environ.get("MCP_FILESYSTEM_COMMAND", "npx")
        args_str = os.environ.get("MCP_FILESYSTEM_ARGS", "-y @modelcontextprotocol/server-filesystem /app/mcp_workspace")
        args = args_str.split()

        configs.append(MCPServerConfig(
            name="filesystem",
            transport="stdio",
            command=command,
            args=args,
            enabled=True
        ))
        mcp_logger.info(f"Loaded filesystem server config: command={command}, args={args}")

    # GitHub server
    if os.environ.get("MCP_GITHUB_ENABLED", "false").lower() == "true":
        command = os.environ.get("MCP_GITHUB_COMMAND", "npx")
        args_str = os.environ.get("MCP_GITHUB_ARGS", "-y @modelcontextprotocol/server-github")
        args = args_str.split()

        env = {}
        github_token = os.environ.get("MCP_GITHUB_TOKEN")
        if github_token:
            env["GITHUB_TOKEN"] = github_token

        configs.append(MCPServerConfig(
            name="github",
            transport="stdio",
            command=command,
            args=args,
            env=env if env else None,
            enabled=True
        ))
        mcp_logger.info(f"Loaded github server config: command={command}, args={args}")

    mcp_logger.info(f"Loaded {len(configs)} MCP server configurations from environment")
    return configs
