"""Example usage of ChEMBL tool.

This script demonstrates how to:
1. Initialize the ChEMBL tool
2. Search for compounds by target
3. Get drug information
4. Search by disease indication
5. Handle results and errors
"""

import sys
import os

# Add parent directory to path to import tools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.chembl_tool import ChEMBLTool


def example_search_by_target():
    """Example 1: Search for compounds by protein target."""
    print("=" * 60)
    print("Example 1: Search Compounds by Target")
    print("=" * 60)

    # Initialize tool
    chembl = ChEMBLTool()

    # Search for EGFR inhibitors
    print("\nSearching for EGFR inhibitors...")
    result = chembl.search_by_target("EGFR", max_results=5)

    if result.success:
        print(f"\nFound {len(result.data)} compounds:")
        print(f"Query took {result.metadata['latency_ms']}ms")
        print()

        for i, compound in enumerate(result.data, 1):
            print(f"{i}. {compound['name']}")
            print(f"   ChEMBL ID: {compound['chembl_id']}")
            print(f"   Type: {compound['molecule_type']}")
            print(f"   Development Phase: {compound['development_phase']}")
            print(f"   Molecular Weight: {compound['molecular_weight']}")
            print(f"   Mechanism: {compound['mechanism_of_action']}")
            print(f"   URL: {compound['url']}")
            print()
    else:
        print(f"Error: {result.error}")


def example_get_drug_info():
    """Example 2: Get detailed drug information."""
    print("=" * 60)
    print("Example 2: Get Drug Information by ChEMBL ID")
    print("=" * 60)

    chembl = ChEMBLTool()

    # Get info for Gefitinib (CHEMBL941)
    print("\nGetting information for Gefitinib (CHEMBL941)...")
    result = chembl.get_drug_info("CHEMBL941")

    if result.success:
        drug = result.data
        print(f"\nName: {drug['name']}")
        print(f"ChEMBL ID: {drug['chembl_id']}")
        print(f"Type: {drug['molecule_type']}")
        print(f"Development Phase: {drug['development_phase']}")
        print(f"Max Phase: {drug['max_phase']}")
        print(f"Molecular Weight: {drug['molecular_weight']}")
        print(f"AlogP: {drug['alogp']}")

        if drug['mechanisms']:
            print(f"\nMechanisms of Action:")
            for mech in drug['mechanisms']:
                print(f"  - {mech['action']}")
                print(f"    Target: {mech['target']}")
    else:
        print(f"Error: {result.error}")


def example_search_by_indication():
    """Example 3: Search drugs by disease indication."""
    print("=" * 60)
    print("Example 3: Search Drugs by Indication")
    print("=" * 60)

    chembl = ChEMBLTool()

    # Search for lung cancer drugs
    print("\nSearching for lung cancer drugs...")
    result = chembl.search_by_indication("lung cancer", max_results=10)

    if result.success:
        print(f"\nFound {len(result.data)} drugs:")

        # Group by max phase
        phase_groups = {}
        for drug in result.data:
            phase = drug['max_phase']
            if phase not in phase_groups:
                phase_groups[phase] = []
            phase_groups[phase].append(drug)

        for phase in sorted(phase_groups.keys(), reverse=True):
            phase_name = {4: "Approved", 3: "Phase 3", 2: "Phase 2", 1: "Phase 1", 0: "Preclinical"}.get(phase, f"Phase {phase}")
            print(f"\n{phase_name}:")
            for drug in phase_groups[phase][:3]:  # Show top 3 per phase
                print(f"  - {drug['drug_name']}: {drug['indication']}")
    else:
        print(f"Error: {result.error}")


def example_different_targets():
    """Example 4: Search multiple targets."""
    print("=" * 60)
    print("Example 4: Search Multiple Targets")
    print("=" * 60)

    chembl = ChEMBLTool()

    targets = ["HER2", "VEGFR", "BRAF"]

    for target in targets:
        print(f"\nSearching for {target} inhibitors...")
        result = chembl.search_by_target(target, max_results=3)

        if result.success:
            print(f"Found {len(result.data)} compounds:")
            for compound in result.data:
                print(f"  - {compound['name']} ({compound['development_phase']})")
        else:
            print(f"Error: {result.error}")


def example_compare_compounds():
    """Example 5: Compare multiple compounds."""
    print("=" * 60)
    print("Example 5: Compare Multiple Compounds")
    print("=" * 60)

    chembl = ChEMBLTool()

    # Compare some EGFR inhibitors
    compounds = [
        ("CHEMBL941", "Gefitinib"),
        ("CHEMBL1201585", "Erlotinib"),
        ("CHEMBL1173655", "Afatinib")
    ]

    print("\nComparing EGFR inhibitors:")
    print(f"\n{'Name':<15} {'Phase':<12} {'MW':<10} {'LogP':<10}")
    print("-" * 50)

    for chembl_id, name in compounds:
        result = chembl.get_drug_info(chembl_id)

        if result.success:
            drug = result.data
            print(f"{drug['name']:<15} {drug['development_phase']:<12} "
                  f"{str(drug['molecular_weight']):<10} {str(drug['alogp']):<10}")
        else:
            print(f"{name:<15} Error: {result.error}")


def example_caching():
    """Example 6: Demonstrate caching."""
    print("=" * 60)
    print("Example 6: Caching Demonstration")
    print("=" * 60)

    chembl = ChEMBLTool()

    # First search
    print("\nFirst search (should hit API)...")
    result1 = chembl.search_by_target("EGFR", max_results=3)
    if result1.success:
        print(f"Query took {result1.metadata['latency_ms']}ms")
        print(f"Cached: {result1.metadata.get('cached', False)}")

    # Second identical search
    print("\nSecond identical search (should use cache)...")
    result2 = chembl.search_by_target("EGFR", max_results=3)
    if result2.success:
        print(f"Query took {result2.metadata['latency_ms']}ms")
        print(f"Cached: {result2.metadata.get('cached', False)}")
        print(f"Speed improvement: {result1.metadata['latency_ms'] / max(result2.metadata['latency_ms'], 1):.1f}x faster")


def example_error_handling():
    """Example 7: Error handling."""
    print("=" * 60)
    print("Example 7: Error Handling")
    print("=" * 60)

    chembl = ChEMBLTool()

    # Try to get info for invalid ChEMBL ID
    print("\nTrying to get info for invalid ChEMBL ID...")
    result = chembl.get_drug_info("INVALID_ID_12345")

    if result.success:
        print("Received data (unexpected)")
    else:
        print(f"Error (expected): {result.error}")
        print("Error handling working correctly!")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("ChEMBL Tool Examples")
    print("=" * 60)

    try:
        example_search_by_target()
        print("\n")

        example_get_drug_info()
        print("\n")

        example_search_by_indication()
        print("\n")

        example_different_targets()
        print("\n")

        example_compare_compounds()
        print("\n")

        example_caching()
        print("\n")

        example_error_handling()

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
