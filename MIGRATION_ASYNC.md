# Миграция на AsyncTeleBot

**Дата:** 2026-02-08
**Версия:** 2.0 (Async)

## 🎯 Цель миграции

Устранение блокировок при одновременных запросах от разных пользователей путем перехода на полностью асинхронную архитектуру.

## 🔧 Основные изменения

### 1. **core/telegram.py** - AsyncTeleBot
```python
# Было:
bot = telebot.TeleBot(TG_BOT_TOKEN, threaded=False)

# Стало:
from telebot.async_telebot import AsyncTeleBot
bot = AsyncTeleBot(TG_BOT_TOKEN)
```

### 2. **bot.py** - async entry point
- Добавлен `async def main()`
- Используется `asyncio.run(main())`
- Убран `run_async()` из warmup и shutdown

### 3. **ai/processor.py** - async processing
- `def process_text_message()` → `async def process_text_message()`
- `run_async(mcp_manager.get_all_tools())` → `await mcp_manager.get_all_tools()`
- `tool_executor.execute_tool_loop()` → `await tool_executor.execute_tool_loop()`

### 4. **ai/tool_executor.py** - async tool execution
- `def execute_tool_loop()` → `async def execute_tool_loop()`
- `def _execute_single_tool_call()` → `async def _execute_single_tool_call()`
- `run_async(mcp_manager.execute_tool())` → `await mcp_manager.execute_tool()`

### 5. **handlers/** - все handlers стали async
Все handlers в следующих файлах:
- `handlers/messages.py`
- `handlers/commands.py`
- `handlers/admin_commands.py`
- `handlers/mcp_commands.py`
- `handlers/voice.py`

Изменения:
- `def handler()` → `async def handler()`
- `bot.reply_to()` → `await bot.reply_to()`
- `bot.send_message()` → `await bot.send_message()`
- И т.д. для всех bot методов

### 6. **utils/messaging.py** - async messaging
- `def send_long_message()` → `async def send_long_message()`
- `def _send_message_chunks()` → `async def _send_message_chunks()`

### 7. **utils/typing_indicator.py** - async typing
Полностью переписан с использованием `asyncio`:
- Threading заменен на `asyncio.Task`
- `threading.Event` → `asyncio.create_task()` + `task.cancel()`
- Более эффективное управление асинхронными задачами

### 8. **core/async_helpers.py** - deprecated
Файл помечен как deprecated и оставлен только для обратной совместимости.

## 📊 Преимущества

### До миграции (синхронный код):
```
User A: [===== 30s =====]
User B:                    [===== 30s =====]  ← ждет User A
User C:                                         [===== 30s =====]  ← ждет A и B
```
**Проблема:** Блокировки, один запрос блокирует другие

### После миграции (асинхронный код):
```
User A: [===== 30s =====]
User B: [===== 30s =====]  ← обрабатывается параллельно
User C: [===== 30s =====]  ← обрабатывается параллельно
```
**Результат:** Истинная concurrent обработка, никаких блокировок

## ⚡ Улучшения производительности

1. **Никаких блокировок** - каждый запрос обрабатывается независимо
2. **Лучшая масштабируемость** - сотни одновременных пользователей
3. **Чище код** - убраны все `run_async()` костыли
4. **Нативная асинхронность** - весь код теперь async/await

## 🧪 Тестирование

### Ручное тестирование
1. Запустите бота: `python bot.py`
2. Отправьте несколько сообщений с разных аккаунтов одновременно
3. Убедитесь, что все обрабатываются параллельно

### Проверка логов
```bash
# Должны увидеть параллельную обработку:
API request started: chat_id=123, model=glm-4.7
API request started: chat_id=456, model=glm-4.7  ← сразу после первого
API response received: chat_id=123, duration=27.01s
API response received: chat_id=456, duration=26.54s
```

## ⚠️ Обратная совместимость

### Что может сломаться:
1. **Декораторы** - если используются кастомные декораторы, они должны поддерживать async
2. **External библиотеки** - если используются sync-only библиотеки, может потребоваться обертка
3. **Тесты** - unit тесты нужно обновить для работы с async

### Deprecated код:
- `core/async_helpers.py` - помечен как deprecated, но оставлен для совместимости
- Импорты `from core.async_helpers import run_async` можно удалить

## 📝 Чеклист миграции

- [x] core/telegram.py - AsyncTeleBot
- [x] bot.py - async entry point
- [x] ai/processor.py - async processing
- [x] ai/tool_executor.py - async tool execution
- [x] handlers/messages.py - async handlers
- [x] handlers/commands.py - async handlers
- [x] handlers/admin_commands.py - async handlers
- [x] handlers/mcp_commands.py - async handlers
- [x] handlers/voice.py - async handler
- [x] utils/messaging.py - async messaging
- [x] utils/typing_indicator.py - async typing
- [x] Удалены все `run_async()` вызовы
- [x] core/async_helpers.py - deprecated

## 🔄 Откат (если нужно)

Если что-то пошло не так, можно откатиться через git:
```bash
git log --oneline  # Найдите коммит до миграции
git revert HEAD    # Откатить последний коммит
# или
git reset --hard <commit-hash>  # Жесткий откат
```

## 📚 Дополнительные ресурсы

- [AsyncTeleBot документация](https://github.com/eternnoir/pyTelegramBotAPI#asynchronous-telebot)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [Async/Await в Python](https://realpython.com/async-io-python/)

---

**Автор:** Claude AI (migracja na AsyncTeleBot)
**Проверено:** 2026-02-08
