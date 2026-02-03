"""
AI message processing with MCP tool support.
"""

import base64
from config import MAX_HISTORY_LENGTH, MAX_VISION_TOKENS, MCP_MAX_ITERATIONS, API_MAX_RETRIES
from core.openai_client import client
from core.async_helpers import run_async
from core.telegram import app_logger
from storage.chat_history import get_chat_history, save_chat_history, clear_chat_history
from storage.user_settings import get_user_model, should_use_mcp_for_user
from ai.tool_executor import ToolExecutor

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

    # Tool calling loop (extracted to ToolExecutor)
    message = chat_completion.choices[0].message

    if message.tool_calls:
        tool_executor = ToolExecutor(mcp_manager, client, max_iterations=MCP_MAX_ITERATIONS)
        ai_response, max_iterations_reached = tool_executor.execute_tool_loop(
            message, history, model, max_tokens, tools_param
        )
    else:
        # No tool calls - use message content directly
        ai_response = message.content if message.content else "No response."

    history_text_only.append({"role": "assistant", "content": ai_response})

    app_logger.info(
        f"AI response: chat_id={chat_id}, model={model}, "
        f"response_length={len(ai_response)}, response_preview='{ai_response[:200]}...'"
    )

    # Save current chat history
    save_chat_history(chat_id, history_text_only)

    return ai_response
