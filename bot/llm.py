"""Tiny async LLM client for the @-mention chatbot.

Uses Groq (free tier, OpenAI-shaped API). This module is the ONLY place that
knows which provider/model we talk to — to switch models or providers later,
change it here and keep chat()'s signature the same.
"""

import os

from groq import AsyncGroq

# Groq rotates its hosted models occasionally — if calls start 400ing with a
# "model_decommissioned" error, pick a current one from https://console.groq.com/docs/models
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = AsyncGroq()  # reads GROQ_API_KEY from the environment
    return _client


async def chat(messages, max_tokens=600):
    """messages is an OpenAI-style list of {role, content} dicts (system first).
    Returns the reply text. Raises on API error so the caller can post a
    friendly fallback."""
    resp = await _get_client().chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=messages,
    )
    return (resp.choices[0].message.content or '').strip()
