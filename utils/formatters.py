"""
Text formatting utilities for Telegram messages.
"""

import re
import html as html_module


def escape_html(text):
    """Экранирует HTML спецсимволы"""
    if not text:
        return ""
    return html_module.escape(str(text))


def markdown_to_html(text):
    """
    Конвертирует Markdown в Telegram HTML.
    Поддерживает: **bold**, *italic*, `code`, ```code blocks```, [links](url),
    ~~strikethrough~~, заголовки (#), списки (-)

    Обрабатывает форматирование в правильном порядке, чтобы избежать конфликтов.
    """
    if not text:
        return ""

    # Сохраняем code blocks и inline code, заменяя их на плейсхолдеры
    code_blocks = []
    inline_codes = []

    # Code blocks (```...```) - используем \x00 как маркер, чтобы избежать конфликтов
    def save_code_block(match):
        code = match.group(1)
        placeholder = f"\x00CODEBLOCK\x00{len(code_blocks)}\x00"
        code_blocks.append(f'<pre>{escape_html(code)}</pre>')
        return placeholder

    result = re.sub(r'```(.*?)```', save_code_block, text, flags=re.DOTALL)

    # Inline code (`...`)
    def save_inline_code(match):
        code = match.group(1)
        placeholder = f"\x00INLINECODE\x00{len(inline_codes)}\x00"
        inline_codes.append(f'<code>{escape_html(code)}</code>')
        return placeholder

    result = re.sub(r'`([^`]+)`', save_inline_code, result)

    # Экранируем HTML спецсимволы в обычном тексте
    result = escape_html(result)

    # Восстанавливаем плейсхолдеры (они уже экранированы, но нам нужны оригинальные)
    for i in range(len(code_blocks)):
        result = result.replace(escape_html(f"\x00CODEBLOCK\x00{i}\x00"), f"\x00CODEBLOCK\x00{i}\x00")
    for i in range(len(inline_codes)):
        result = result.replace(escape_html(f"\x00INLINECODE\x00{i}\x00"), f"\x00INLINECODE\x00{i}\x00")

    # Теперь обрабатываем остальное форматирование (текст уже экранирован)

    # Заголовки (### Header) - конвертируем в bold с переносами
    # H1: # Header → <b>📌 Header</b>
    result = re.sub(r'^# (.+)$', r'<b>📌 \1</b>', result, flags=re.MULTILINE)
    # H2: ## Header → <b>▸ Header</b>
    result = re.sub(r'^## (.+)$', r'<b>▸ \1</b>', result, flags=re.MULTILINE)
    # H3: ### Header → <b>• \1</b>
    result = re.sub(r'^### (.+)$', r'<b>• \1</b>', result, flags=re.MULTILINE)
    # H4-H6: просто bold
    result = re.sub(r'^#{4,6} (.+)$', r'<b>\1</b>', result, flags=re.MULTILINE)

    # Списки (- item или * item) - добавляем bullet point
    result = re.sub(r'^[\-\*] (.+)$', r'  • \1', result, flags=re.MULTILINE)
    # Нумерованные списки (1. item)
    result = re.sub(r'^(\d+)\. (.+)$', r'  \1. \2', result, flags=re.MULTILINE)

    # Links [text](url) - обрабатываем до bold/italic
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2)
        return f'<a href="{url}">{link_text}</a>'
    result = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, result)

    # Bold (**text**) - используем non-greedy match
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)

    # Italic (*text*) - только одиночные звездочки, не жадный match
    result = re.sub(r'(?<!\*)\*(?!\*)(.+?)\*(?!\*)', r'<i>\1</i>', result)

    # Strikethrough (~~text~~)
    result = re.sub(r'~~(.+?)~~', r'<s>\1</s>', result)

    # Underline (__text__)
    result = re.sub(r'__(.+?)__', r'<u>\1</u>', result)

    # Восстанавливаем code blocks
    for i, code_html in enumerate(code_blocks):
        result = result.replace(f"\x00CODEBLOCK\x00{i}\x00", code_html)

    # Восстанавливаем inline code
    for i, code_html in enumerate(inline_codes):
        result = result.replace(f"\x00INLINECODE\x00{i}\x00", code_html)

    return result


def escape_markdown_v2(text_with_markup):
    """Экранирует спецсимволы для MarkdownV2 (для системных сообщений бота)"""
    chars = r'_\*\[\]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(chars)}])', r'\\\1', str(text_with_markup))
