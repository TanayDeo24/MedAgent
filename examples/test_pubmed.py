"""Example usage of PubMed tool.

This script demonstrates how to:
1. Initialize the PubMed tool
2. Search for scientific papers
3. Get paper details
4. Handle results and errors
"""

import sys
import os

# Add parent directory to path to import tools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.pubmed_tool import PubMedTool


def example_basic_search():
    """Example 1: Basic search for papers."""
    print("=" * 60)
    print("Example 1: Basic PubMed Search")
    print("=" * 60)

    # Initialize tool
    pubmed = PubMedTool()

    # Search for EGFR inhibitors in lung cancer
    print("\nSearching for 'EGFR inhibitors lung cancer'...")
    result = pubmed.search_pubmed(
        "EGFR inhibitors lung cancer",
        max_results=5
    )

    if result.success:
        print(f"\nFound {len(result.data)} papers:")
        print(f"Query took {result.metadata['latency_ms']}ms")
        print()

        for i, paper in enumerate(result.data, 1):
            print(f"{i}. {paper['title']}")
            print(f"   PMID: {paper['pmid']}")
            print(f"   Authors: {', '.join(paper['authors'][:3])}")
            if len(paper['authors']) > 3:
                print(f"            et al.")
            print(f"   Year: {paper['year']}")
            print(f"   Journal: {paper['journal']}")
            print(f"   URL: {paper['url']}")
            print()
    else:
        print(f"Error: {result.error}")


def example_get_paper_details():
    """Example 2: Get details for a specific paper."""
    print("=" * 60)
    print("Example 2: Get Paper Details by PMID")
    print("=" * 60)

    pubmed = PubMedTool()

    # First, search for a paper
    result = pubmed.search_pubmed("pembrolizumab lung cancer", max_results=1)

    if result.success and result.data:
        pmid = result.data[0]['pmid']
        print(f"\nGetting details for PMID: {pmid}...")

        # Get detailed information
        details_result = pubmed.get_paper_details(pmid)

        if details_result.success and details_result.data:
            paper = details_result.data[0]
            print(f"\nTitle: {paper['title']}")
            print(f"\nAbstract:")
            print(paper['abstract'][:500] + "..." if len(paper['abstract']) > 500 else paper['abstract'])
            print(f"\nAuthors: {', '.join(paper['authors'])}")
            print(f"Publication Date: {paper['pub_date']}")
            if paper['doi']:
                print(f"DOI: {paper['doi']}")
    else:
        print("Could not find papers for the search")


def example_date_filtering():
    """Example 3: Search with date filtering."""
    print("=" * 60)
    print("Example 3: Search with Date Filtering")
    print("=" * 60)

    pubmed = PubMedTool()

    # Search for recent papers (last 1 year)
    print("\nSearching for papers from the last year...")
    result = pubmed.search_pubmed(
        "immunotherapy cancer",
        max_results=5,
        years_back=1
    )

    if result.success:
        print(f"\nFound {len(result.data)} recent papers:")
        for paper in result.data:
            print(f"- {paper['title']} ({paper['year']})")
    else:
        print(f"Error: {result.error}")


def example_error_handling():
    """Example 4: Error handling."""
    print("=" * 60)
    print("Example 4: Error Handling")
    print("=" * 60)

    pubmed = PubMedTool()

    # Try to get details for an invalid PMID
    print("\nTrying to get details for invalid PMID...")
    result = pubmed.get_paper_details("invalid_pmid_12345")

    if result.success:
        if result.data:
            print("Received data (unexpected)")
        else:
            print("No data found for this PMID")
    else:
        print(f"Error (expected): {result.error}")
        print("Error handling working correctly!")


def example_caching():
    """Example 5: Demonstrate caching."""
    print("=" * 60)
    print("Example 5: Caching Demonstration")
    print("=" * 60)

    pubmed = PubMedTool()

    # First search
    print("\nFirst search (should hit API)...")
    result1 = pubmed.search_pubmed("cancer immunotherapy", max_results=3)
    if result1.success:
        print(f"Query took {result1.metadata['latency_ms']}ms")
        print(f"Cached: {result1.metadata.get('cached', False)}")

    # Second identical search
    print("\nSecond identical search (should use cache)...")
    result2 = pubmed.search_pubmed("cancer immunotherapy", max_results=3)
    if result2.success:
        print(f"Query took {result2.metadata['latency_ms']}ms")
        print(f"Cached: {result2.metadata.get('cached', False)}")
        print(f"Speed improvement: {result1.metadata['latency_ms'] / max(result2.metadata['latency_ms'], 1):.1f}x faster")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("PubMed Tool Examples")
    print("=" * 60)

    try:
        example_basic_search()
        print("\n")

        example_get_paper_details()
        print("\n")

        example_date_filtering()
        print("\n")

        example_error_handling()
        print("\n")

        example_caching()

    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user.")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
