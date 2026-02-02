"""
OpenAI client initialization.
"""

import openai
from config import OPENAI_API_KEY, OPENAI_BASE_URL

# Create OpenAI client
client = openai.Client(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)
