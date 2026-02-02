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
    """Simplified MCP server manager that creates fresh connections for each use"""

    def __init__(self, server_configs: List[MCPServerConfig]):
        self.configs = [c for c in server_configs if c.enabled]
        self._tool_cache = {}  # {tool_name: server_name}
        self._cache_timestamp = 0
        self._cache_ttl = 300  # 5 minutes
        mcp_logger.info(f"MCPServerManager initialized with {len(self.configs)} configs")

    @asynccontextmanager
    async def connect_to_server(self, config: MCPServerConfig):
        """Context manager for connecting to a single server"""
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
        all_tools = []
        import time

        for config in self.configs:
            try:
                async with self.connect_to_server(config) as session:
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

        # Update cache timestamp
        self._cache_timestamp = time.time()
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

        # Try to use cache first
        server_name = None
        if self._is_cache_valid() and tool_name in self._tool_cache:
            server_name = self._tool_cache[tool_name]
            mcp_logger.info(f"Using cached server '{server_name}' for tool '{tool_name}'")

            # Find config by name
            config = next((c for c in self.configs if c.name == server_name), None)

            if config:
                try:
                    async with self.connect_to_server(config) as session:
                        mcp_logger.info(f"Executing {tool_name} on {config.name}, args={json.dumps(arguments)[:200]}")

                        # Execute the tool with timeout
                        from config import MCP_TOOL_TIMEOUT_SECONDS
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments),
                            timeout=MCP_TOOL_TIMEOUT_SECONDS
                        )

                        duration = time.time() - start_time
                        result_str = str(result)
                        mcp_logger.info(f"Tool executed: {tool_name}, duration={duration:.2f}s, result_size={len(result_str)} chars")

                        # Extract content from result
                        if hasattr(result, 'content') and result.content:
                            if len(result.content) > 0:
                                content_item = result.content[0]
                                if hasattr(content_item, 'text'):
                                    return content_item.text
                                else:
                                    return str(content_item)
                            return str(result.content)
                        return str(result)

                except asyncio.TimeoutError:
                    error_msg = f"Tool '{tool_name}' execution timed out after 30 seconds"
                    mcp_logger.error(error_msg)
                    raise Exception(error_msg)
                except Exception as e:
                    # Use exception() to log full traceback
                    mcp_logger.exception(f"Cached server failed, falling back to search: {e}")
                    # Cache was wrong, remove this entry and fall through to search
                    self._tool_cache.pop(tool_name, None)

        # Cache miss or cache failed - search all servers
        mcp_logger.info(f"Cache miss for tool '{tool_name}', searching all servers")

        for config in self.configs:
            try:
                async with self.connect_to_server(config) as session:
                    # List tools to see if this server has the requested tool
                    tools_result = await session.list_tools()
                    has_tool = any(tool.name == tool_name for tool in tools_result.tools)

                    if has_tool:
                        # Update cache
                        self._tool_cache[tool_name] = config.name

                        mcp_logger.info(f"Executing {tool_name} on {config.name}, args={json.dumps(arguments)[:200]}")

                        # Execute the tool with timeout
                        from config import MCP_TOOL_TIMEOUT_SECONDS
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments),
                            timeout=MCP_TOOL_TIMEOUT_SECONDS
                        )

                        duration = time.time() - start_time
                        result_str = str(result)
                        mcp_logger.info(f"Tool executed: {tool_name}, duration={duration:.2f}s, result_size={len(result_str)} chars")

                        # Extract content from result
                        if hasattr(result, 'content') and result.content:
                            if len(result.content) > 0:
                                content_item = result.content[0]
                                if hasattr(content_item, 'text'):
                                    return content_item.text
                                else:
                                    return str(content_item)
                            return str(result.content)
                        return str(result)

            except asyncio.TimeoutError:
                from config import MCP_TOOL_TIMEOUT_SECONDS
                error_msg = f"Tool '{tool_name}' execution timed out after {MCP_TOOL_TIMEOUT_SECONDS} seconds"
                mcp_logger.error(error_msg)
                raise Exception(error_msg)
            except Exception as e:
                # Use exception() to log full traceback
                mcp_logger.exception(f"Error checking {config.name} for tool {tool_name}: {e}")
                continue

        raise Exception(f"Tool '{tool_name}' not found in any connected server")

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
