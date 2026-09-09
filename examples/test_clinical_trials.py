"""Example usage of ClinicalTrials tool.

This script demonstrates how to:
1. Initialize the ClinicalTrials tool
2. Search for clinical trials by condition
3. Filter by intervention and status
4. Get trial details
5. Handle results and errors
"""

import sys
import os

# Add parent directory to path to import tools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.clinical_trials_tool import ClinicalTrialsTool


def example_basic_search():
    """Example 1: Basic search for clinical trials."""
    print("=" * 60)
    print("Example 1: Basic Clinical Trials Search")
    print("=" * 60)

    # Initialize tool
    ct = ClinicalTrialsTool()

    # Search for lung cancer trials
    print("\nSearching for recruiting lung cancer trials...")
    result = ct.search_trials(
        condition="lung cancer",
        status="RECRUITING",
        max_results=5
    )

    if result.success:
        print(f"\nFound {len(result.data)} trials:")
        print(f"Query took {result.metadata['latency_ms']}ms")
        print()

        for i, trial in enumerate(result.data, 1):
            print(f"{i}. {trial['title'][:80]}...")
            print(f"   NCT ID: {trial['nct_id']}")
            print(f"   Status: {trial['status']}")
            print(f"   Phase: {trial['phase']}")
            print(f"   Sponsor: {trial['sponsor']}")
            print(f"   URL: {trial['url']}")
            print()
    else:
        print(f"Error: {result.error}")


def example_intervention_search():
    """Example 2: Search by condition and intervention."""
    print("=" * 60)
    print("Example 2: Search by Condition and Intervention")
    print("=" * 60)

    ct = ClinicalTrialsTool()

    # Search for lung cancer trials with pembrolizumab
    print("\nSearching for lung cancer trials with pembrolizumab...")
    result = ct.search_trials(
        condition="lung cancer",
        intervention="pembrolizumab",
        status="RECRUITING",
        max_results=3
    )

    if result.success:
        print(f"\nFound {len(result.data)} trials:")

        for trial in result.data:
            print(f"\n{trial['title'][:80]}...")
            print(f"NCT ID: {trial['nct_id']}")
            print(f"Phase: {trial['phase']}")

            print(f"Conditions: {', '.join(trial['conditions'][:3])}")

            print("Interventions:")
            for intervention in trial['interventions'][:3]:
                print(f"  - {intervention['type']}: {intervention['name']}")

            if trial['locations']:
                print(f"Sample location: {trial['locations'][0]}")
    else:
        print(f"Error: {result.error}")


def example_phase_filtering():
    """Example 3: Filter by trial phase."""
    print("=" * 60)
    print("Example 3: Filter by Trial Phase")
    print("=" * 60)

    ct = ClinicalTrialsTool()

    # Search for Phase 3 trials
    print("\nSearching for Phase 3 lung cancer trials...")
    result = ct.search_trials(
        condition="lung cancer",
        phase="PHASE3",
        status="RECRUITING",
        max_results=5
    )

    if result.success:
        print(f"\nFound {len(result.data)} Phase 3 trials:")

        for trial in result.data:
            print(f"\n- {trial['title'][:70]}...")
            print(f"  NCT ID: {trial['nct_id']}")
            print(f"  Enrollment: {trial['enrollment']}")
            print(f"  Start Date: {trial['start_date']}")
    else:
        print(f"Error: {result.error}")


def example_get_trial_details():
    """Example 4: Get details for a specific trial."""
    print("=" * 60)
    print("Example 4: Get Trial Details by NCT ID")
    print("=" * 60)

    ct = ClinicalTrialsTool()

    # First, search for a trial
    result = ct.search_trials(
        condition="lung cancer",
        max_results=1
    )

    if result.success and result.data:
        nct_id = result.data[0]['nct_id']
        print(f"\nGetting details for {nct_id}...")

        # Get detailed information
        details_result = ct.get_trial_details(nct_id)

        if details_result.success and details_result.data:
            trial = details_result.data[0]
            print(f"\nTitle: {trial['title']}")
            print(f"\nStatus: {trial['status']}")
            print(f"Phase: {trial['phase']}")
            print(f"Sponsor: {trial['sponsor']}")
            print(f"Enrollment: {trial['enrollment']}")
            print(f"\nBrief Summary:")
            print(trial['brief_summary'][:300] + "...")
            print(f"\nConditions: {', '.join(trial['conditions'])}")

            if trial['interventions']:
                print("\nInterventions:")
                for intervention in trial['interventions'][:5]:
                    print(f"  - {intervention['type']}: {intervention['name']}")

            if trial['locations']:
                print(f"\nNumber of locations: {len(trial['locations'])}")
                print("Sample locations:")
                for location in trial['locations'][:3]:
                    print(f"  - {location}")
    else:
        print("Could not find trials for the search")


def example_different_statuses():
    """Example 5: Search trials with different statuses."""
    print("=" * 60)
    print("Example 5: Search by Different Statuses")
    print("=" * 60)

    ct = ClinicalTrialsTool()

    statuses = ["RECRUITING", "COMPLETED"]

    for status in statuses:
        print(f"\nSearching for {status} lung cancer trials...")
        result = ct.search_trials(
            condition="lung cancer",
            status=status,
            max_results=3
        )

        if result.success:
            print(f"Found {len(result.data)} {status} trials")
            for trial in result.data:
                print(f"  - {trial['title'][:60]}... ({trial['nct_id']})")
        else:
            print(f"Error: {result.error}")


def example_caching():
    """Example 6: Demonstrate caching."""
    print("=" * 60)
    print("Example 6: Caching Demonstration")
    print("=" * 60)

    ct = ClinicalTrialsTool()

    # First search
    print("\nFirst search (should hit API)...")
    result1 = ct.search_trials(
        condition="diabetes",
        status="RECRUITING",
        max_results=3
    )
    if result1.success:
        print(f"Query took {result1.metadata['latency_ms']}ms")
        print(f"Cached: {result1.metadata.get('cached', False)}")

    # Second identical search
    print("\nSecond identical search (should use cache)...")
    result2 = ct.search_trials(
        condition="diabetes",
        status="RECRUITING",
        max_results=3
    )
    if result2.success:
        print(f"Query took {result2.metadata['latency_ms']}ms")
        print(f"Cached: {result2.metadata.get('cached', False)}")
        print(f"Speed improvement: {result1.metadata['latency_ms'] / max(result2.metadata['latency_ms'], 1):.1f}x faster")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("ClinicalTrials Tool Examples")
    print("=" * 60)

    try:
        example_basic_search()
        print("\n")

        example_intervention_search()
        print("\n")

        example_phase_filtering()
        print("\n")

        example_get_trial_details()
        print("\n")

        example_different_statuses()
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
