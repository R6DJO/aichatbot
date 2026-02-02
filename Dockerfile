FROM python:3.11-alpine

WORKDIR /app

# Install Node.js and npm for MCP servers
RUN apk add --no-cache nodejs npm ca-certificates curl openssl && \
    update-ca-certificates

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем непривилегированного пользователя
RUN addgroup -S botuser && adduser -S botuser -G botuser

# Создаем папку для MCP workspace с правильными правами
RUN mkdir -p /app/mcp_workspace && \
    chown -R botuser:botuser /app/mcp_workspace

# Копируем код бота (модульная структура)
COPY --chown=botuser:botuser bot.py .
COPY --chown=botuser:botuser config.py .
COPY --chown=botuser:botuser mcp_manager.py .
COPY --chown=botuser:botuser core/ ./core/
COPY --chown=botuser:botuser storage/ ./storage/
COPY --chown=botuser:botuser auth/ ./auth/
COPY --chown=botuser:botuser models/ ./models/
COPY --chown=botuser:botuser ai/ ./ai/
COPY --chown=botuser:botuser handlers/ ./handlers/
COPY --chown=botuser:botuser utils/ ./utils/

# Переключаемся на непривилегированного пользователя
USER botuser

# Запускаем бота
CMD ["python", "bot.py"]
