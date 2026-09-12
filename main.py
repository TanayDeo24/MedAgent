#!/usr/bin/env python3
"""Command-line entrypoint for MedAgent.

Usage:
    python main.py "your research query here"
    python main.py --trace "your research query here"
    python main.py --max-iterations 5 --temperature 0.2 "your research query here"
"""

import argparse
import sys

from config.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MedAgent - Autonomous Drug Discovery Research Assistant"
    )
    parser.add_argument("query", help="The research question to investigate")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print the tool-call history and reasoning trace after the report",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum self-reflection loops before the agent must stop (default: 10)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="LLM temperature for the agent's reasoning nodes (default: 0.3)",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help=(
            "Disable RAG retrieval (retrieval.retriever.retrieve()) in "
            "synthesis_node - reproduces the pre-RAG pipeline exactly. "
            "Default is RAG enabled."
        ),
    )
    args = parser.parse_args()

    if not settings.NVIDIA_API_KEY:
        print(
            "Error: NVIDIA_API_KEY is not set.\n"
            "MedAgent requires an NVIDIA NIM API key to run its LLM reasoning nodes.\n"
            "Add it to a .env file (see .env.example) or export it in your shell:\n"
            "  export NVIDIA_API_KEY=your_api_key_here\n\n"
            "Get an API key from: https://build.nvidia.com/",
            file=sys.stderr,
        )
        return 1

    # Imported after the API-key check so a missing key fails fast with a clear
    # message instead of an import-time crash deep inside langchain_nvidia_ai_endpoints.
    from agent.graph import MedAgent

    agent = MedAgent(
        max_iterations=args.max_iterations,
        temperature=args.temperature,
        use_rag=not args.no_rag,
    )

    print(f"Running MedAgent on query: {args.query}\n")
    result = agent.run(args.query)

    if args.trace:
        agent.print_reasoning_trace(result, detailed=True)

    print("=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(result.get("final_report", "No report generated"))

    if result.get("errors"):
        print("\n" + "=" * 70)
        print("ERRORS ENCOUNTERED DURING RUN")
        print("=" * 70)
        for error in result["errors"]:
            print(f"- {error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
