"""
Tool execution handler for MCP (Model Context Protocol).

Handles iterative tool calling loop with OpenAI API.
"""

import json
import time
from core.telegram import app_logger


class ToolExecutor:
    """
    Handles MCP tool execution loop.

    Executes tools iteratively until:
    - No more tool calls
    - Max iterations reached
    - API error occurs
    """

    def __init__(self, mcp_manager, client, max_iterations=5):
        """
        Initialize tool executor.

        Args:
            mcp_manager: MCP server manager instance
            client: OpenAI client instance
            max_iterations: Maximum tool call iterations (default: 5)
        """
        self.mcp_manager = mcp_manager
        self.client = client
        self.max_iterations = max_iterations

    async def execute_tool_loop(self, initial_message, history, model, max_tokens, tools_param):
        """
        Execute tool calls iteratively until complete or max iterations reached.

        Args:
            initial_message: Initial API response message (may contain tool_calls)
            history: Conversation history (will be modified in-place)
            model: Model name
            max_tokens: Max tokens for API call
            tools_param: Available tools for OpenAI API

        Returns:
            Tuple[str, bool]: (final_response, max_iterations_reached)
        """
        message = initial_message
        iteration = 0

        while message.tool_calls and iteration < self.max_iterations:
            iteration += 1
            app_logger.info(
                f"Tool calls (iteration {iteration}): "
                f"{[tc.function.name for tc in message.tool_calls]}"
            )

            # Add assistant message with tool calls to history
            self._add_tool_call_to_history(history, message)

            # Execute each tool call
            for tool_call in message.tool_calls:
                result = await self._execute_single_tool_call(tool_call)
                self._add_tool_result_to_history(history, tool_call, result)

            # Get next response from API with tool results
            try:
                start_time = time.time()
                app_logger.info(f"API request started (iteration {iteration}): model={model}, messages={len(history)}, tools={len(tools_param) if tools_param else 0}")

                chat_completion = self.client.chat.completions.create(
                    model=model,
                    messages=history,
                    max_tokens=max_tokens,
                    tools=tools_param,
                    tool_choice="auto" if tools_param else None
                )

                duration = time.time() - start_time
                message = chat_completion.choices[0].message
                app_logger.info(f"API response received (iteration {iteration}): model={model}, duration={duration:.2f}s, has_tool_calls={bool(message.tool_calls)}")
            except Exception as e:
                app_logger.error(f"API error during tool call iteration: {e}")
                break

        # Check if we hit max iterations
        max_iterations_reached = iteration >= self.max_iterations
        if max_iterations_reached:
            app_logger.warning(
                f"Max tool call iterations ({self.max_iterations}) reached"
            )

        # Extract final response
        final_response = (
            message.content if message.content
            else "I used tools but couldn't generate a text response."
        )

        return final_response, max_iterations_reached

    async def _execute_single_tool_call(self, tool_call):
        """
        Execute a single tool and return result.

        Args:
            tool_call: OpenAI tool call object

        Returns:
            Tool execution result (str or dict)
        """
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        try:
            result = await self.mcp_manager.execute_tool(tool_name, tool_args)
            app_logger.info(
                f"Tool executed: {tool_name}, result_length={len(str(result))}"
            )
            return result

        except Exception as e:
            error_msg = f"Error executing tool {tool_name}: {str(e)}"
            app_logger.error(error_msg)
            return {"error": error_msg}

    def _add_tool_call_to_history(self, history, message):
        """
        Add assistant message with tool calls to conversation history.

        Args:
            history: Conversation history (modified in-place)
            message: OpenAI message with tool_calls
        """
        history.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]
        })

    def _add_tool_result_to_history(self, history, tool_call, result):
        """
        Add tool result to conversation history.

        Args:
            history: Conversation history (modified in-place)
            tool_call: OpenAI tool call object
            result: Tool execution result
        """
        # Convert result to string if needed
        if isinstance(result, dict):
            content = json.dumps(result)
        elif isinstance(result, str):
            content = result
        else:
            content = str(result)

        history.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": content
        })
