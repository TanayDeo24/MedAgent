#!/usr/bin/env python3
"""Demo script for MedAgent Phase 2.

This script demonstrates the full capabilities of the autonomous MedAgent:
- LLM-powered query analysis
- Autonomous research planning
- Dynamic tool selection
- Cross-reference synthesis
- Self-reflection loop
- Professional report generation

Run this to see the agent in action!
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.graph import MedAgent


def demo_simple_query():
    """Demo 1: Simple query with one iteration."""
    print("\n" + "=" * 70)
    print("DEMO 1: Simple Query - \"What is erlotinib?\"")
    print("=" * 70)
    print("\nThis demonstrates a straightforward query that the agent")
    print("can answer in a single research iteration.\n")

    agent = MedAgent(max_iterations=3, temperature=0.3)

    query = "What is erlotinib?"
    print(f"Query: {query}\n")
    print("Running agent (this may take 30-60 seconds)...\n")

    result = agent.run(query)

    # Show reasoning trace
    agent.print_reasoning_trace(result, detailed=True)

    # Show report
    print("=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(result.get("final_report", "No report generated"))
    print("\n")

    # Save report
    filepath = agent.save_report(result)
    print(f"Report saved to: {filepath}\n")


def demo_complex_query():
    """Demo 2: Complex query that may trigger self-reflection loop."""
    print("\n" + "=" * 70)
    print("DEMO 2: Complex Query - \"Find EGFR inhibitors for non-small cell lung cancer\"")
    print("=" * 70)
    print("\nThis demonstrates a more complex query that may require")
    print("multiple research iterations as the agent self-reflects")
    print("and decides it needs more information.\n")

    agent = MedAgent(max_iterations=5, temperature=0.3)

    query = "Find EGFR inhibitors for non-small cell lung cancer"
    print(f"Query: {query}\n")
    print("Running agent (this may take 1-2 minutes)...\n")

    result = agent.run(query)

    # Show reasoning trace
    agent.print_reasoning_trace(result, detailed=True)

    # Show some key metrics
    print("=" * 70)
    print("KEY METRICS")
    print("=" * 70)
    print(f"Research iterations: {result['current_step']}/{result['max_iterations']}")
    print(f"Final confidence: {result['confidence_score']:.2f}")
    print(f"Tools used: {agent.get_tool_usage_stats(result)['tools_called']}")
    print(f"Total API calls: {agent.get_tool_usage_stats(result)['total_calls']}")
    print(f"Total results found: {agent.get_tool_usage_stats(result)['total_results']}")
    print(f"Citations: {len(agent.get_citations(result))}")
    print("")

    # Show report
    print("=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(result.get("final_report", "No report generated"))
    print("\n")

    # Save report
    filepath = agent.save_report(result)
    print(f"Report saved to: {filepath}\n")


def demo_clinical_trials():
    """Demo 3: Clinical trials focused query."""
    print("\n" + "=" * 70)
    print("DEMO 3: Clinical Trials Query")
    print("=" * 70)
    print("\nDemonstrates the agent's ability to focus on clinical trial data.\n")

    agent = MedAgent(max_iterations=3, temperature=0.3)

    query = "What are the active clinical trials for pembrolizumab in melanoma?"
    print(f"Query: {query}\n")
    print("Running agent...\n")

    result = agent.run(query)

    # Just show summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    stats = agent.get_tool_usage_stats(result)
    print(f"Tools used: {', '.join(stats['tools_called'])}")
    print(f"Results found: {stats['total_results']}")
    print(f"Confidence: {result['confidence_score']:.2f}")
    print(f"\nReport length: {len(result.get('final_report', ''))} characters")

    # Save report
    filepath = agent.save_report(result)
    print(f"Report saved to: {filepath}\n")


def demo_comparison():
    """Demo 4: Compare different agent configurations."""
    print("\n" + "=" * 70)
    print("DEMO 4: Configuration Comparison")
    print("=" * 70)
    print("\nCompares agent behavior with different temperatures.\n")

    query = "What is gefitinib?"

    # Configuration 1: Low temperature (more deterministic)
    print("Configuration 1: temperature=0.1 (deterministic)")
    agent1 = MedAgent(max_iterations=2, temperature=0.1)
    result1 = agent1.run(query)
    print(f"  Tools selected: {agent1.get_tool_usage_stats(result1)['tools_called']}")
    print(f"  Confidence: {result1['confidence_score']:.2f}")

    # Configuration 2: Higher temperature (more creative)
    print("\nConfiguration 2: temperature=0.5 (creative)")
    agent2 = MedAgent(max_iterations=2, temperature=0.5)
    result2 = agent2.run(query)
    print(f"  Tools selected: {agent2.get_tool_usage_stats(result2)['tools_called']}")
    print(f"  Confidence: {result2['confidence_score']:.2f}")

    print("\nNote: Higher temperature may lead to different tool selection")
    print("and research strategies, but results should still be grounded in data.\n")


def interactive_mode():
    """Interactive mode: User enters queries."""
    print("\n" + "=" * 70)
    print("MEDAGENT INTERACTIVE MODE")
    print("=" * 70)
    print("\nEnter drug discovery queries and get autonomous research reports!")
    print("Type 'quit' to exit.\n")

    agent = MedAgent(max_iterations=5, temperature=0.3)

    while True:
        try:
            query = input("\nEnter your query: ").strip()

            if query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not query:
                print("Please enter a query.")
                continue

            print(f"\nResearching: {query}")
            print("Please wait (this may take 1-2 minutes)...\n")

            result = agent.run(query)

            # Show summary
            print("\n" + "=" * 70)
            print("RESEARCH COMPLETE")
            print("=" * 70)
            stats = agent.get_tool_usage_stats(result)
            print(f"Iterations: {result['current_step']}/{result['max_iterations']}")
            print(f"Tools used: {', '.join(stats['tools_called'])}")
            print(f"Results found: {stats['total_results']}")
            print(f"Confidence: {result['confidence_score']:.2f}")

            # Ask if user wants to see full report
            show_report = input("\nShow full report? (y/n): ").strip().lower()
            if show_report == 'y':
                print("\n" + "=" * 70)
                print("REPORT")
                print("=" * 70)
                print(result.get("final_report", "No report generated"))

            # Ask if user wants to save
            save = input("\nSave report to file? (y/n): ").strip().lower()
            if save == 'y':
                filepath = agent.save_report(result)
                print(f"Report saved to: {filepath}")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print("Please try again.")


def main():
    """Main demo selector."""
    print("=" * 70)
    print("MEDAGENT PHASE 2 DEMO")
    print("Autonomous Drug Discovery Research Assistant")
    print("=" * 70)
    print("\nSelect a demo:")
    print("  1. Simple query (fast, single iteration)")
    print("  2. Complex query (may trigger self-reflection loop)")
    print("  3. Clinical trials focused query")
    print("  4. Configuration comparison")
    print("  5. Interactive mode (enter your own queries)")
    print("  6. Run all demos")
    print("  0. Exit")

    choice = input("\nEnter choice (0-6): ").strip()

    if choice == "1":
        demo_simple_query()
    elif choice == "2":
        demo_complex_query()
    elif choice == "3":
        demo_clinical_trials()
    elif choice == "4":
        demo_comparison()
    elif choice == "5":
        interactive_mode()
    elif choice == "6":
        demo_simple_query()
        demo_complex_query()
        demo_clinical_trials()
        demo_comparison()
    elif choice == "0":
        print("Goodbye!")
    else:
        print("Invalid choice. Please run again.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
