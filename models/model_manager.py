"""
Model management (fetching available models from API).
"""

import requests
from collections import defaultdict
from config import OPENAI_BASE_URL, OPENAI_API_KEY


def fetch_models():
    """Получить список моделей из API и сгруппировать по производителю"""
    try:
        models_url = f"{OPENAI_BASE_URL.rstrip('/')}/models"
        headers = {}
        if OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

        response = requests.get(
            models_url,
            headers=headers,
            timeout=5
        )
        response.raise_for_status()
        data = response.json()

        # Группируем модели по owned_by
        models_by_owner = defaultdict(list)
        for model in data.get("data", []):
            owner = model.get("owned_by", "unknown")
            model_id = model.get("id", "")
            if model_id:
                models_by_owner[owner].append(model_id)

        return dict(models_by_owner)
    except Exception as e:
        print(f"Error fetching models: {e}")
        # Возврат к дефолтному списку при ошибке
        return {
            "z.ai": ["glm-4.7"],
            "qwen": ["qwen3-coder-plus"],
            "openai": ["gpt-5.2"],
        }
