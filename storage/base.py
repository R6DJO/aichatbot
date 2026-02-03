"""
Base repository for S3 storage operations.

Provides a generic repository pattern to centralize S3 operations
and reduce duplication across storage modules.
"""

import json
from typing import TypeVar, Generic, Callable, Any, Optional
from config import S3_BUCKET
from storage.s3_client import get_s3_client
from core.telegram import app_logger


T = TypeVar('T')


class S3Repository(Generic[T]):
    """
    Generic repository for S3 storage operations.

    Args:
        key_pattern: S3 key pattern with {id} placeholder (e.g., "{id}.json")
        default_factory: Factory function for default value (e.g., dict, list)

    Example:
        >>> chat_repo = S3Repository("{id}.json", default_factory=list)
        >>> history = chat_repo.get("12345")  # Returns [] if not found
        >>> chat_repo.save("12345", [{"role": "user", "content": "hi"}])
    """

    def __init__(
        self,
        key_pattern: str,
        default_factory: Callable[[], T] = dict
    ):
        """
        Initialize S3 repository.

        Args:
            key_pattern: S3 key pattern with {id} placeholder
            default_factory: Callable that returns default value
        """
        self.key_pattern = key_pattern
        self.default_factory = default_factory
        self.s3_client = get_s3_client()

    def _get_key(self, id: str) -> str:
        """Generate S3 key from ID."""
        return self.key_pattern.format(id=id)

    def get(self, id: str) -> T:
        """
        Get object from S3 or return default.

        Args:
            id: Object identifier (chat_id, user_id, etc.)

        Returns:
            Object from S3 or default value if not found

        Raises:
            Exception: If S3 operation fails (except NoSuchKey)
        """
        key = self._get_key(id)
        try:
            response = self.s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            return json.loads(response["Body"].read())
        except self.s3_client.exceptions.NoSuchKey:
            return self.default_factory()
        except Exception as exc:
            app_logger.error(
                f"Failed to get {key}: bucket={S3_BUCKET}, error={exc}"
            )
            raise

    def save(self, id: str, data: T) -> bool:
        """
        Save object to S3.

        Args:
            id: Object identifier
            data: Object to save (will be JSON-serialized)

        Returns:
            True if successful, False otherwise
        """
        key = self._get_key(id)
        try:
            self.s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=json.dumps(data)
            )
            return True
        except Exception as exc:
            app_logger.error(
                f"Failed to save {key}: bucket={S3_BUCKET}, error={exc}"
            )
            return False

    def delete(self, id: str) -> bool:
        """
        Delete object from S3.

        Args:
            id: Object identifier

        Returns:
            True if successful, False otherwise
        """
        key = self._get_key(id)
        try:
            self.s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
            return True
        except Exception as exc:
            app_logger.error(
                f"Failed to delete {key}: bucket={S3_BUCKET}, error={exc}"
            )
            return False

    def exists(self, id: str) -> bool:
        """
        Check if object exists in S3.

        Args:
            id: Object identifier

        Returns:
            True if object exists, False otherwise
        """
        key = self._get_key(id)
        try:
            self.s3_client.head_object(Bucket=S3_BUCKET, Key=key)
            return True
        except self.s3_client.exceptions.NoSuchKey:
            return False
        except Exception as exc:
            app_logger.error(
                f"Failed to check existence of {key}: bucket={S3_BUCKET}, error={exc}"
            )
            return False
