"""
MCP (Model Context Protocol) command handlers.
"""

from core.telegram import bot, app_logger
from core.async_helpers import run_async
from storage.user_settings import should_use_mcp_for_user, set_mcp_for_user
from utils.decorators import require_auth, log_command, handle_errors
import ai.processor  # For accessing mcp_manager


@bot.message_handler(commands=["tools"])
@require_auth()
@log_command
@handle_errors("❌ Error listing tools.")
def list_tools(message):
    if not ai.processor.mcp_manager:
        bot.reply_to(message, "🔧 MCP tools are not enabled.")
        return

    tools = run_async(ai.processor.mcp_manager.get_all_tools())

    if not tools:
        bot.reply_to(message, "🔧 No MCP tools available.")
        return

    # Format tool list grouped by server
    tools_text = "🔧 *Available MCP Tools:*\n\n"

    tools_by_server = {}
    for tool in tools:
        server_name = tool.get("_mcp_server", "unknown")
        if server_name not in tools_by_server:
            tools_by_server[server_name] = []
        tools_by_server[server_name].append(tool["function"])

    for server, server_tools in sorted(tools_by_server.items()):
        tools_text += f"📦 *{server}* ({len(server_tools)} tools)\n"
        for tool_func in server_tools:
            name = tool_func["name"]
            # Just show tool name, no description (to keep message short)
            tools_text += f"  - `{name}`\n"
        tools_text += "\n"

    mcp_status = "✅ enabled" if should_use_mcp_for_user(message.chat.id) else "❌ disabled"
    tools_text += f"💡 MCP tools for you: {mcp_status}\n"
    tools_text += "Use `/mcp on` or `/mcp off` to toggle.\n"
    tools_text += f"\nTotal: {len(tools)} tools available."

    # Check if message is too long (Telegram limit is 4096 chars)
    if len(tools_text) > 4000:
        # Split into multiple messages
        messages = []
        current_msg = "🔧 *Available MCP Tools:*\n\n"

        for server, server_tools in sorted(tools_by_server.items()):
            server_section = f"📦 *{server}* ({len(server_tools)} tools)\n"
            for tool_func in server_tools:
                server_section += f"  - `{tool_func['name']}`\n"
            server_section += "\n"

            if len(current_msg) + len(server_section) > 3500:
                messages.append(current_msg)
                current_msg = ""

            current_msg += server_section

        if current_msg:
            current_msg += f"\n💡 MCP tools: {mcp_status}\n"
            current_msg += f"Total: {len(tools)} tools"
            messages.append(current_msg)

        # Send multiple messages
        for msg in messages:
            bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.reply_to(message, tools_text, parse_mode="Markdown")


@bot.message_handler(commands=["mcp"])
@require_auth()
@log_command
def toggle_mcp(message):
    if not ai.processor.mcp_manager:
        bot.reply_to(message, "🔧 MCP tools are not available.")
        return

    args = message.text.split("/mcp")[1].strip().lower()

    if args == "on":
        set_mcp_for_user(message.chat.id, True)
        bot.reply_to(message, "✅ MCP tools enabled.")
    elif args == "off":
        set_mcp_for_user(message.chat.id, False)
        bot.reply_to(message, "❌ MCP tools disabled.")
    else:
        current_status = "enabled" if should_use_mcp_for_user(message.chat.id) else "disabled"
        bot.reply_to(
            message,
            f"🔧 *MCP Tools:* {current_status}\n\n"
            f"`/mcp on` - enable tools\n"
            f"`/mcp off` - disable tools\n"
            f"`/tools` - list available tools",
            parse_mode="Markdown"
        )
