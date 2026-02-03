# MinIO Setup Guide

## Быстрый старт

### 1. Запуск MinIO

```bash
docker-compose up -d
```

MinIO будет доступен:
- **API**: http://localhost:9000
- **Консоль**: http://localhost:9001

### 2. Настройка окружения

Скопируй и отредактируй `.env`:

```bash
cp .env.example .env
```

Обнови переменные для MinIO:
```bash
S3_KEY_ID=minioadmin
S3_KEY_SECRET=minioadmin123
S3_BUCKET=aichatbot
MINIO_ENDPOINT=http://localhost:9000
```

### 3. Проверка подключения

```bash
source venv/bin/activate
pip install boto3

python3 << 'EOF'
import boto3
import os

s3 = boto3.client('s3',
    endpoint_url='http://localhost:9000',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin123'
)

# Создать бакет
try:
    s3.create_bucket(Bucket='aichatbot')
    print("Бакет создан")
except:
    print("Бакет уже существует")

# Тест записи
s3.put_object(Bucket='aichatbot', Key='test.txt', Body='Hello MinIO!')
print("Файл записан")

# Тест чтения
response = s3.get_object(Bucket='aichatbot', Key='test.txt')
print(f"Содержимое: {response['Body'].read().decode()}")
EOF
```

## Управление через CLI

Установка MinIO Client:

```bash
# Linux/macOS
wget https://dl.min.io/client/mc/release/linux-amd64/mc
chmod +x mc
sudo mv mc /usr/local/bin/

# Или через Docker
docker run --rm -it --entrypoint /bin/sh minio/mc
```

Настройка алиаса:

```bash
mc alias set local http://localhost:9000 minioadmin minioadmin123
```

Полезные команды:

```bash
# Список бакетов
mc ls local

# Создать бакет
mc mb local/aichatbot

# Загрузить файл
mc cp myfile.txt local/aichatbot/

# Скачать файл
mc cp local/aichatbot/myfile.txt .

# Удалить файл
mc rm local/aichatbot/myfile.txt

# Удалить бакет
mc rb local/aichatbot --force

# Показать использование диска
mc admin info local
```

## Создание отдельного пользователя (рекомендуется)

### Через веб-консоль:

1. Открой http://localhost:9001
2. Войди: `minioadmin` / `minioadmin123`
3. **Identity** → **Service Accounts** → **Create Service Account**
4. Скопируй Access Key и Secret Key

### Через CLI:

```bash
# Создать пользователя
mc admin user add local botuser password123

# Создать политику
mc admin policy set local readwrite user=botuser

# Получить список пользователей
mc admin user list local
```

Обнови `.env`:
```bash
S3_KEY_ID=botuser
S3_KEY_SECRET=password123
```

## Политики доступа

Создай файл `policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": ["arn:aws:s3:::aichatbot/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::aichatbot"]
    }
  ]
}
```

Применить:
```bash
mc admin policy create local bot-policy policy.json
mc admin policy attach local bot-policy --user=botuser
```

## Продакшен-установка

### Сертификаты (HTTPS)

```yaml
services:
  minio:
    environment:
      - MINIO_CERTS_DIR=/certs
    volumes:
      - ./certs:/certs
```

Сертификаты положить в `./certs/public.crt` и `./certs/private.key`

### Кластер (4 сервера)

```yaml
services:
  minio1:
    image: minio/minio
    command: server http://minio{1...4}/data{1...2}
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin123
    volumes:
      - data1-1:/data1
      - data1-2:/data2

  minio2:
    # ... аналогично
  minio3:
    # ... аналогично
  minio4:
    # ... аналогично
```

### Резервное копирование

```bash
# Зеркалирование бакета
mc mirror local/aichatbot /backup/aichatbot

# На другой MinIO сервер
mc mirror local/aichatbot remote/aichatbot
```

## Мониторинг

Prometheus метрики доступны по адресу:
```
http://localhost:9000/minio/prometheus/metrics
```

## Проблемы и решения

| Проблема | Решение |
|----------|---------|
| Контейнер не стартует | `docker logs minio` — проверь логи |
| Ошибка подключения | Проверь порты: `netstat -tlnp \| grep 9000` |
| Данные потерялись после перезапуска | Проверь volume: `docker volume inspect minio_data` |
| Нет доступа к бакету | Проверь политику пользователя |

## Полезные ссылки

- [Документация MinIO](https://min.io/docs/minio/linux/index.html)
- [S3 API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/)
- [MC Cheat Sheet](https://min.io/docs/minio/linux/reference/minio-mc.html)
