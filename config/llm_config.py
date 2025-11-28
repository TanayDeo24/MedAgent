"""LLM configuration for MedAgent using Google Gemini 1.5 Flash.

This module provides utilities to initialize and configure the Google Gemini LLM
for use in the MedAgent autonomous research assistant.
"""

import os
from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_llm(
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 30,
    model: str = "gemini-pro"
) -> ChatGoogleGenerativeAI:
    """Initialize Google Gemini 1.5 Flash LLM with specified parameters.

    Uses the FREE tier of Google Gemini which has the following limits:
    - 15 requests per minute
    - 1,500 requests per day
    - 1M token context window
    - No cost for usage within limits

    Args:
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative).
                    Default 0.3 for balanced reasoning.
        max_tokens: Maximum tokens in response. Default 2048.
        timeout: Request timeout in seconds. Default 30.
        model: Gemini model name. Default "gemini-1.5-flash".

    Returns:
        Configured ChatGoogleGenerativeAI instance ready for use.

    Raises:
        ValueError: If GOOGLE_API_KEY environment variable is not set.

    Example:
        >>> from config.llm_config import get_llm
        >>> llm = get_llm(temperature=0.5)
        >>> response = llm.invoke("What are EGFR inhibitors?")
        >>> print(response.content)

    Note:
        To get a free API key:
        1. Visit https://makersuite.google.com/app/apikey
        2. Sign in with Google account
        3. Create API key
        4. Add to .env file as: GOOGLE_API_KEY=your_key_here
    """
    # Get API key from environment
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY not found in environment variables.\n"
            "Please add your API key to the .env file:\n"
            "  GOOGLE_API_KEY=your_key_here\n\n"
            "Get a free API key from: https://makersuite.google.com/app/apikey"
        )

    # Initialize and return the LLM
    # Using gemini-flash-latest (FREE tier, fast, capable)
    return ChatGoogleGenerativeAI(
        model="gemini-flash-latest",
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=max_tokens,
        timeout=timeout,
    )


def test_llm_connection() -> bool:
    """Test if LLM connection is working.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        llm = get_llm()
        response = llm.invoke("Say 'Connection successful' and nothing else.")
        return "successful" in response.content.lower()
    except Exception as e:
        print(f"LLM connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Quick test when run directly
    print("Testing Gemini LLM connection...")

    if test_llm_connection():
        print("✓ LLM connection successful!")

        # Show example usage
        llm = get_llm()
        response = llm.invoke("What is an EGFR inhibitor in one sentence?")
        print(f"\nExample response:\n{response.content}")
    else:
        print("✗ LLM connection failed. Check your API key.")
