#!/usr/bin/env python3
"""Validation script for MedAgent tools.

This script validates that all tools are working correctly by:
1. Testing each tool independently
2. Verifying rate limiting works
3. Checking error handling
4. Printing a summary report
"""

import sys
import time
from typing import Dict, List, Tuple

# Add current directory to path
sys.path.insert(0, ".")

from tools.pubmed_tool import PubMedTool
from tools.clinical_trials_tool import ClinicalTrialsTool
from tools.chembl_tool import ChEMBLTool


class ValidationReport:
    """Track validation results."""

    def __init__(self):
        self.results: List[Tuple[str, bool, str]] = []

    def add(self, test_name: str, passed: bool, message: str = ""):
        """Add a test result."""
        self.results.append((test_name, passed, message))

    def print_report(self):
        """Print validation report."""
        print("\n" + "=" * 60)
        print("VALIDATION REPORT")
        print("=" * 60)

        passed = sum(1 for _, p, _ in self.results if p)
        total = len(self.results)

        for test_name, passed_test, message in self.results:
            status = "✓" if passed_test else "✗"
            print(f"{status} {test_name}")
            if message:
                print(f"  {message}")

        print("=" * 60)
        print(f"Results: {passed}/{total} tests passed")
        print("=" * 60)

        return passed == total


def validate_pubmed_tool(report: ValidationReport):
    """Validate PubMed tool."""
    print("\n" + "-" * 60)
    print("Testing PubMed Tool...")
    print("-" * 60)

    try:
        tool = PubMedTool()
        report.add("PubMed tool initialization", True)

        # Test basic search
        print("  Running basic search...")
        result = tool.search_pubmed("cancer immunotherapy", max_results=2)
        if result.success and result.data:
            report.add("PubMed basic search", True, f"Found {len(result.data)} papers")
        else:
            report.add("PubMed basic search", False, result.error or "No results")

        # Test rate limiting (make rapid calls)
        print("  Testing rate limiting...")
        start_time = time.time()
        for _ in range(4):
            tool.search_pubmed("test", max_results=1)
        elapsed = time.time() - start_time

        # Should take at least 1 second for 4 calls at 3 req/sec
        if elapsed >= 0.5:
            report.add("PubMed rate limiting", True, f"Took {elapsed:.2f}s for 4 calls")
        else:
            report.add("PubMed rate limiting", False, "Rate limiting may not be working")

        # Test error handling
        print("  Testing error handling...")
        result = tool.search_pubmed("", max_results=1)
        if not result.success or isinstance(result.error, str):
            report.add("PubMed error handling", True, "Handles errors gracefully")
        else:
            report.add("PubMed error handling", False, "Error handling failed")

        # Test result parsing
        print("  Testing result parsing...")
        result = tool.search_pubmed("EGFR inhibitors", max_results=1)
        if result.success and result.data:
            paper = result.data[0]
            has_required_fields = all(
                field in paper
                for field in ["pmid", "title", "authors", "journal"]
            )
            if has_required_fields:
                report.add("PubMed result parsing", True, "All fields present")
            else:
                report.add("PubMed result parsing", False, "Missing fields")
        else:
            report.add("PubMed result parsing", False, "No results to parse")

        # Test caching
        print("  Testing caching...")
        result1 = tool.search_pubmed("test query xyz", max_results=1)
        result2 = tool.search_pubmed("test query xyz", max_results=1)
        if result2.success and result2.metadata.get("cached"):
            report.add("PubMed caching", True, "Cache hit on second call")
        else:
            report.add("PubMed caching", False, "Cache not working")

    except Exception as e:
        report.add("PubMed tool", False, f"Exception: {str(e)}")


def validate_clinical_trials_tool(report: ValidationReport):
    """Validate ClinicalTrials tool."""
    print("\n" + "-" * 60)
    print("Testing ClinicalTrials Tool...")
    print("-" * 60)

    try:
        tool = ClinicalTrialsTool()
        report.add("ClinicalTrials tool initialization", True)

        # Test basic search
        print("  Running basic search...")
        result = tool.search_trials(condition="lung cancer", max_results=2)
        if result.success and result.data:
            report.add("ClinicalTrials basic search", True, f"Found {len(result.data)} trials")
        else:
            report.add("ClinicalTrials basic search", False, result.error or "No results")

        # Test filtering
        print("  Testing phase filtering...")
        result = tool.search_trials(
            condition="cancer",
            phase="PHASE3",
            max_results=2
        )
        if result.success:
            report.add("ClinicalTrials phase filtering", True)
        else:
            report.add("ClinicalTrials phase filtering", False, result.error)

        # Test result parsing
        print("  Testing result parsing...")
        result = tool.search_trials(condition="diabetes", max_results=1)
        if result.success and result.data:
            trial = result.data[0]
            has_required_fields = all(
                field in trial
                for field in ["nct_id", "title", "status", "phase"]
            )
            if has_required_fields:
                report.add("ClinicalTrials result parsing", True, "All fields present")
            else:
                report.add("ClinicalTrials result parsing", False, "Missing fields")
        else:
            report.add("ClinicalTrials result parsing", False, "No results to parse")

        # Test caching
        print("  Testing caching...")
        result1 = tool.search_trials(condition="test disease xyz", max_results=1)
        result2 = tool.search_trials(condition="test disease xyz", max_results=1)
        if result2.metadata.get("cached"):
            report.add("ClinicalTrials caching", True, "Cache hit on second call")
        else:
            report.add("ClinicalTrials caching", False, "Cache not working")

    except Exception as e:
        report.add("ClinicalTrials tool", False, f"Exception: {str(e)}")


def validate_chembl_tool(report: ValidationReport):
    """Validate ChEMBL tool."""
    print("\n" + "-" * 60)
    print("Testing ChEMBL Tool...")
    print("-" * 60)

    try:
        tool = ChEMBLTool()
        report.add("ChEMBL tool initialization", True)

        # Test target search
        print("  Running target search...")
        result = tool.search_by_target("EGFR", max_results=2)
        if result.success and result.data:
            report.add("ChEMBL target search", True, f"Found {len(result.data)} compounds")
        else:
            report.add("ChEMBL target search", False, result.error or "No results")

        # Test drug info retrieval
        print("  Testing drug info retrieval...")
        result = tool.get_drug_info("CHEMBL941")
        if result.success and result.data:
            report.add("ChEMBL drug info retrieval", True)
        else:
            report.add("ChEMBL drug info retrieval", False, result.error or "Failed")

        # Test indication search
        print("  Testing indication search...")
        result = tool.search_by_indication("lung cancer", max_results=2)
        if result.success:
            report.add("ChEMBL indication search", True, f"Found {len(result.data)} drugs")
        else:
            report.add("ChEMBL indication search", False, result.error)

        # Test result parsing
        print("  Testing result parsing...")
        result = tool.search_by_target("HER2", max_results=1)
        if result.success and result.data:
            compound = result.data[0]
            has_required_fields = all(
                field in compound
                for field in ["chembl_id", "name", "development_phase"]
            )
            if has_required_fields:
                report.add("ChEMBL result parsing", True, "All fields present")
            else:
                report.add("ChEMBL result parsing", False, "Missing fields")
        else:
            report.add("ChEMBL result parsing", False, "No results to parse")

        # Test caching
        print("  Testing caching...")
        result1 = tool.search_by_target("BRAF", max_results=1)
        result2 = tool.search_by_target("BRAF", max_results=1)
        if result2.metadata.get("cached"):
            report.add("ChEMBL caching", True, "Cache hit on second call")
        else:
            report.add("ChEMBL caching", False, "Cache not working")

    except Exception as e:
        report.add("ChEMBL tool", False, f"Exception: {str(e)}")


def main():
    """Run all validations."""
    print("\n" + "=" * 60)
    print("MEDAGENT VALIDATION SUITE")
    print("=" * 60)
    print("\nThis will test all tools with real API calls.")
    print("It may take 30-60 seconds to complete.\n")

    response = input("Continue? (y/n): ")
    if response.lower() != 'y':
        print("Validation cancelled.")
        return

    report = ValidationReport()

    try:
        validate_pubmed_tool(report)
        validate_clinical_trials_tool(report)
        validate_chembl_tool(report)

    except KeyboardInterrupt:
        print("\n\nValidation interrupted by user.")
        return

    # Print final report
    all_passed = report.print_report()

    if all_passed:
        print("\n✓ All tools validated successfully!")
        print("  MedAgent Day 1 is ready to use.")
        sys.exit(0)
    else:
        print("\n✗ Some validations failed.")
        print("  Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
