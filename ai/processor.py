"""
AI message processing with MCP tool support.
"""

import json
import base64
from config import MAX_HISTORY_LENGTH, MAX_VISION_TOKENS, MCP_MAX_ITERATIONS, API_MAX_RETRIES
from core.openai_client import client
from core.async_helpers import run_async
from core.telegram import app_logger
from storage.chat_history import get_chat_history, save_chat_history, clear_chat_history
from storage.user_settings import get_user_model, should_use_mcp_for_user

# Global MCP manager instance (set from bot.py)
mcp_manager = None


def process_text_message(text, chat_id, image_content=None):
    """
    Process text message with AI, supporting vision and MCP tools.

    Returns AI response as string.
    """
    # Если есть изображение, используем vision модель
    if image_content is not None:
        model = "gpt-4-vision-preview"
    else:
        model = get_user_model(chat_id)

    app_logger.info(f"Processing message: chat_id={chat_id}, model={model}, has_image={image_content is not None}, text='{text[:200]}...'")

    max_tokens = None

    # Read current chat history
    history = get_chat_history(chat_id)

    # Limit history length to prevent memory overflow and reduce API costs
    if len(history) > MAX_HISTORY_LENGTH:
        old_length = len(history)
        # Keep only the last MAX_HISTORY_LENGTH messages
        history = history[-MAX_HISTORY_LENGTH:]
        app_logger.info(
            f"History trimmed: chat_id={chat_id}, "
            f"old_length={old_length}, new_length={len(history)}"
        )

    history_text_only = history.copy()
    history_text_only.append({"role": "user", "content": text})

    # Add system message to keep responses concise (avoid Telegram 4096 char limit)
    system_message = {
        "role": "system",
        "content": "Keep your responses concise and to the point. Prefer shorter answers over long explanations. If listing items, limit to the most important ones. Maximum response length: ~3000 characters."
    }
    history = [system_message] + history

    if image_content is not None:
        model = "gpt-4-vision-preview"
        max_tokens = MAX_VISION_TOKENS
        base64_image_content = base64.b64encode(image_content).decode("utf-8")
        base64_image_content = f"data:image/jpeg;base64,{base64_image_content}"
        history.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": base64_image_content}},
                ],
            }
        )
    else:
        history.append({"role": "user", "content": text})

    # Get MCP tools if enabled
    tools_param = None
    if mcp_manager and should_use_mcp_for_user(chat_id):
        try:
            tools_param = run_async(mcp_manager.get_all_tools())
            app_logger.info(f"MCP tools available: {len(tools_param)} tools")
        except Exception as e:
            app_logger.error(f"MCP failed, continuing without tools: {e}")
            tools_param = None  # Graceful degradation

    try:
        chat_completion = client.chat.completions.create(
            model=model,
            messages=history,
            max_tokens=max_tokens,
            tools=tools_param,
            tool_choice="auto" if tools_param else None
        )
    except Exception as e:
        app_logger.error(f"API error: chat_id={chat_id}, model={model}, error={str(e)}")
        if type(e).__name__ == "BadRequestError":
            for attempt in range(API_MAX_RETRIES):
                try:
                    app_logger.warning(
                        f"BadRequestError, clearing history and retrying: attempt={attempt + 1}/{API_MAX_RETRIES}, chat_id={chat_id}"
                    )
                    clear_chat_history(chat_id)
                    chat_completion = client.chat.completions.create(
                        model=model,
                        messages=[system_message, {"role": "user", "content": text}],
                        max_tokens=max_tokens,
                        tools=tools_param,
                        tool_choice="auto" if tools_param else None
                    )
                    break
                except Exception as retry_exc:
                    if attempt == API_MAX_RETRIES - 1:
                        app_logger.error(
                            f"Retries exhausted for BadRequestError: chat_id={chat_id}, error={retry_exc}"
                        )
                        return "Произошла ошибка при обработке запроса. Попробуйте позже."
            else:
                return "Произошла ошибка при обработке запроса. Попробуйте позже."
        else:
            raise e

    # Tool calling loop
    message = chat_completion.choices[0].message

    if message.tool_calls:
        iteration = 0

        while message.tool_calls and iteration < MCP_MAX_ITERATIONS:
            iteration += 1
            app_logger.info(f"Tool calls (iteration {iteration}): {[tc.function.name for tc in message.tool_calls]}")

            # Add assistant message with tool calls to history
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

            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                try:
                    result = run_async(
                        mcp_manager.execute_tool(tool_name, tool_args)
                    )

                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(result) if not isinstance(result, str) else result
                    })

                    app_logger.info(f"Tool executed: {tool_name}, result_length={len(str(result))}")

                except Exception as e:
                    error_msg = f"Error executing tool {tool_name}: {str(e)}"
                    app_logger.error(error_msg)

                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps({"error": error_msg})
                    })

            # Retry API call with tool results
            try:
                chat_completion = client.chat.completions.create(
                    model=model,
                    messages=history,
                    max_tokens=max_tokens,
                    tools=tools_param,
                    tool_choice="auto" if tools_param else None
                )
                message = chat_completion.choices[0].message
            except Exception as e:
                app_logger.error(f"API error during tool call iteration: {e}")
                break

        if iteration >= MCP_MAX_ITERATIONS:
            app_logger.warning(f"Max tool call iterations ({MCP_MAX_ITERATIONS}) reached for chat_id={chat_id}")

    # Extract final response
    ai_response = message.content if message.content else "I used tools but couldn't generate a text response."

    history_text_only.append({"role": "assistant", "content": ai_response})

    app_logger.info(
        f"AI response: chat_id={chat_id}, model={model}, "
        f"response_length={len(ai_response)}, response_preview='{ai_response[:200]}...'"
    )

    # Save current chat history
    save_chat_history(chat_id, history_text_only)

    return ai_response
