FROM python:3.11-alpine

WORKDIR /app

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY bot.py .

# Создаем папку для логов
RUN mkdir -p /app/logs

# Запускаем бота
CMD ["python", "bot.py"]
