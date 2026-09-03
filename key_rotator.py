# key_rotator.py
"""
Manages multi-key API rotation using the modern google-genai SDK.
"""

from google import genai
import itertools
from typing import List


class GeminiKeyRotator:
    """Rotates across multiple Gemini API keys automatically, producing isolated client instances."""

    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("No Gemini API keys provided!")
        self.api_keys = api_keys
        self._key_cycle = itertools.cycle(api_keys)

    def get_client(self) -> genai.Client:
        """Returns a configured genai.Client instance with the next rotated API key."""
        key = next(self._key_cycle)
        return genai.Client(api_key=key)

    def get_next_key(self) -> str:
        """Returns the raw next key string."""
        return next(self._key_cycle)