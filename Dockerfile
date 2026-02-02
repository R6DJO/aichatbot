FROM python:3.11-alpine

WORKDIR /app

# Install Node.js and npm for MCP servers
RUN apk add --no-cache nodejs npm ca-certificates && \
    update-ca-certificates 2>/dev/null

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем непривилегированного пользователя
RUN addgroup -S botuser && adduser -S botuser -G botuser

# Создаем папку для MCP workspace с правильными правами
RUN mkdir -p /app/mcp_workspace && \
    chown -R botuser:botuser /app/mcp_workspace

# Копируем код бота
COPY --chown=botuser:botuser bot.py .
COPY --chown=botuser:botuser mcp_manager.py .

# Переключаемся на непривилегированного пользователя
USER botuser

# Запускаем бота
CMD ["python", "bot.py"]
