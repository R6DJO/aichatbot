"""
S3 client creation.
"""

import os
import boto3
from config import S3_KEY_ID, S3_KEY_SECRET


def get_s3_client():
    """Create and return S3 client"""
    session = boto3.session.Session(
        aws_access_key_id=S3_KEY_ID, aws_secret_access_key=S3_KEY_SECRET
    )
    # Используй переменную окружения MINIO_ENDPOINT для своего S3
    endpoint_url = os.environ.get("MINIO_ENDPOINT", "https://storage.yandexcloud.net")
    return session.client(
        service_name="s3", endpoint_url=endpoint_url
    )
