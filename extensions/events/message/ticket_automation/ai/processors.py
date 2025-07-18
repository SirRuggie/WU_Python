# extensions/events/message/ticket_automation/ai/processors.py
"""
AI processing functions for analyzing user responses.
Uses Claude API to intelligently summarize and format responses.
"""

import os
import aiohttp
import json
from typing import Optional

from .prompts import ATTACK_STRATEGIES_PROMPT, CLAN_EXPECTATIONS_PROMPT

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Model configuration
AI_MODEL = "claude-3-haiku-20240307"
MAX_TOKENS = 1000


async def process_attack_strategies_with_ai(existing_summary: str, new_input: str) -> str:
    """
    Process attack strategies using Claude AI.

    Args:
        existing_summary: Current summary of strategies
        new_input: New user input to incorporate

    Returns:
        Updated summary incorporating the new input
    """

    if not ANTHROPIC_API_KEY:
        print("[AI] Warning: ANTHROPIC_API_KEY not set, returning raw input")
        return new_input

    messages = [
        {
            "role": "user",
            "content": f"Existing summary:\n{existing_summary if existing_summary else 'None'}\n\nNew user input:\n{new_input}"
        }
    ]

    try:
        result = await _call_claude_api(messages, ATTACK_STRATEGIES_PROMPT)
        return result if result else existing_summary
    except Exception as e:
        print(f"[AI] Error processing attack strategies: {e}")
        return existing_summary if existing_summary else new_input


async def process_clan_expectations_with_ai(existing_summary: str, new_input: str) -> str:
    """
    Process clan expectations using Claude AI.

    Args:
        existing_summary: Current summary of expectations
        new_input: New user input to incorporate

    Returns:
        Updated summary incorporating the new input
    """

    if not ANTHROPIC_API_KEY:
        print("[AI] Warning: ANTHROPIC_API_KEY not set, returning raw input")
        return new_input

    messages = [
        {
            "role": "user",
            "content": f"Existing summary:\n{existing_summary if existing_summary else 'None'}\n\nNew user input:\n{new_input}"
        }
    ]

    try:
        result = await _call_claude_api(messages, CLAN_EXPECTATIONS_PROMPT)
        return result if result else existing_summary
    except Exception as e:
        print(f"[AI] Error processing clan expectations: {e}")
        return existing_summary if existing_summary else new_input


async def _call_claude_api(messages: list, system_prompt: str) -> Optional[str]:
    """
    Internal function to call Claude API.

    Args:
        messages: List of message dictionaries
        system_prompt: System prompt for the AI

    Returns:
        AI response text or None on error
    """

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": AI_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": messages,
        "system": system_prompt
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANTHROPIC_API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["content"][0]["text"]
                else:
                    error_text = await response.text()
                    print(f"[AI] API error {response.status}: {error_text}")
                    return None
    except aiohttp.ClientError as e:
        print(f"[AI] Network error calling Claude API: {e}")
        return None
    except Exception as e:
        print(f"[AI] Unexpected error calling Claude API: {e}")
        return None