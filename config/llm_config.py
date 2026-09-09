"""LLM configuration for MedAgent using NVIDIA NIM (Nemotron).

This module provides utilities to initialize and configure the NVIDIA NIM-hosted
Nemotron LLM for use in the MedAgent autonomous research assistant.
"""

import os
from typing import Optional
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def get_llm(
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: int = 30,
    model: str = NVIDIA_MODEL
) -> ChatNVIDIA:
    """Initialize NVIDIA NIM Nemotron LLM with specified parameters.

    Uses NVIDIA's hosted NIM endpoint for the Nemotron model family.

    Args:
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative).
                    Default 0.3 for balanced reasoning.
        max_tokens: Maximum tokens in response. Default 2048.
        timeout: Request timeout in seconds. Default 30.
        model: NVIDIA NIM model name. Default "nvidia/nemotron-3-super-120b-a12b".

    Returns:
        Configured ChatNVIDIA instance ready for use.

    Raises:
        ValueError: If NVIDIA_API_KEY environment variable is not set.

    Example:
        >>> from config.llm_config import get_llm
        >>> llm = get_llm(temperature=0.5)
        >>> response = llm.invoke("What are EGFR inhibitors?")
        >>> print(response.content)

    Note:
        To get an NVIDIA API key:
        1. Visit https://build.nvidia.com/
        2. Sign in / create an account
        3. Generate an API key for NIM endpoints
        4. Add to .env file as: NVIDIA_API_KEY=your_key_here
    """
    # Get API key from environment
    api_key = os.getenv("NVIDIA_API_KEY")

    if not api_key:
        raise ValueError(
            "NVIDIA_API_KEY not found in environment variables.\n"
            "Please add your API key to the .env file:\n"
            "  NVIDIA_API_KEY=your_key_here\n\n"
            "Get an API key from: https://build.nvidia.com/"
        )

    # Initialize and return the LLM
    return ChatNVIDIA(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
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
    print("Testing NVIDIA NIM (Nemotron) LLM connection...")

    if test_llm_connection():
        print("✓ LLM connection successful!")

        # Show example usage
        llm = get_llm()
        response = llm.invoke("What is an EGFR inhibitor in one sentence?")
        print(f"\nExample response:\n{response.content}")
    else:
        print("✗ LLM connection failed. Check your API key.")
