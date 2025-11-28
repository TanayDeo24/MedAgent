"""Test cases for MedAgent evaluation.

This module contains a diverse set of drug discovery queries spanning
different difficulty levels and query types. These test cases are designed
to evaluate the agent's performance across realistic research scenarios.

Each test case includes:
- The query itself
- Difficulty level
- Expected tools the agent should use
- Expected findings (drugs, compounds, etc.)
- Success criteria
- Whether multi-step reasoning is required
"""

# =============================================================================
# TEST CASES
# =============================================================================

TEST_CASES = [
    # =========================================================================
    # EASY QUERIES (3 cases)
    # These are straightforward, single-hop queries that should succeed easily
    # =========================================================================

    {
        "id": 1,
        "query": "What are FDA-approved EGFR inhibitors?",
        "difficulty": "easy",
        "expected_tools": ["chembl", "pubmed"],
        "expected_drugs": ["Erlotinib", "Gefitinib", "Afatinib", "Osimertinib"],
        "min_results": 4,
        "success_criteria": "Should find at least 3-4 approved EGFR inhibitors with evidence from ChEMBL and PubMed",
        "reasoning_required": False,
        "notes": "This is a classic drug target query. Agent should use ChEMBL to find approved compounds targeting EGFR."
    },

    {
        "id": 2,
        "query": "What is pembrolizumab used for?",
        "difficulty": "easy",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Pembrolizumab"],
        "min_results": 5,
        "success_criteria": "Should identify pembrolizumab as a PD-1 inhibitor used for multiple cancer types",
        "reasoning_required": False,
        "notes": "Single drug query. Agent should find indication information from trials and literature."
    },

    {
        "id": 3,
        "query": "Find BTK inhibitors",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Ibrutinib", "Acalabrutinib", "Zanubrutinib"],
        "min_results": 3,
        "success_criteria": "Should identify major BTK inhibitors from ChEMBL database",
        "reasoning_required": False,
        "notes": "Straightforward target-based query. ChEMBL should have these well-documented compounds."
    },

    # =========================================================================
    # MEDIUM QUERIES (4 cases)
    # These require multi-hop reasoning or cross-referencing multiple sources
    # =========================================================================

    {
        "id": 4,
        "query": "Find BTK inhibitors in Phase 2 or 3 clinical trials for autoimmune diseases",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Ibrutinib", "Acalabrutinib", "Fenebrutinib"],
        "min_results": 3,
        "success_criteria": "Should find BTK inhibitors AND cross-reference with clinical trials for autoimmune indications",
        "reasoning_required": True,
        "notes": "Requires cross-referencing: First find BTK inhibitors (ChEMBL), then check trials for autoimmune diseases."
    },

    {
        "id": 5,
        "query": "What are the clinical trials for erlotinib in non-small cell lung cancer?",
        "difficulty": "medium",
        "expected_tools": ["clinical_trials", "pubmed"],
        "expected_drugs": ["Erlotinib"],
        "min_results": 5,
        "success_criteria": "Should find multiple trials with NCT IDs, trial phases, and status information",
        "reasoning_required": True,
        "notes": "Specific drug + indication query. Agent should search trials database and validate with literature."
    },

    {
        "id": 6,
        "query": "Which kinase inhibitors are approved for melanoma?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Vemurafenib", "Dabrafenib", "Trametinib"],
        "min_results": 3,
        "success_criteria": "Should identify BRAF/MEK inhibitors approved for melanoma with supporting evidence",
        "reasoning_required": True,
        "notes": "Requires filtering: Find kinase inhibitors (broad), filter for melanoma indication, verify approval status."
    },

    {
        "id": 7,
        "query": "Find PD-1/PD-L1 inhibitors with completed Phase 3 trials",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials"],
        "expected_drugs": ["Pembrolizumab", "Nivolumab", "Atezolizumab", "Durvalumab"],
        "min_results": 4,
        "success_criteria": "Should identify checkpoint inhibitors and verify Phase 3 trial completion status",
        "reasoning_required": True,
        "notes": "Requires verification: Find PD-1/PD-L1 drugs, then filter by completed Phase 3 trials."
    },

    # =========================================================================
    # HARD QUERIES (2 cases)
    # These require complex reasoning, filtering, or handling of nuanced info
    # =========================================================================

    {
        "id": 8,
        "query": "Which protein kinase inhibitors failed in clinical trials due to cardiotoxicity?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": [],  # No specific drugs expected - this is exploratory
        "min_results": 2,
        "success_criteria": "Should identify failed drugs AND provide evidence linking failure to cardiotoxicity",
        "reasoning_required": True,
        "notes": "Very challenging: Must identify (1) kinase inhibitors, (2) that failed, (3) specifically due to cardiotoxicity. Requires deep literature search and reasoning about causality."
    },

    {
        "id": 9,
        "query": "Compare the efficacy of first-generation vs second-generation EGFR TKIs in EGFR-mutant NSCLC",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials", "chembl"],
        "expected_drugs": ["Erlotinib", "Gefitinib", "Afatinib", "Dacomitinib"],
        "min_results": 5,
        "success_criteria": "Should identify both generations, find comparative efficacy data, and synthesize differences",
        "reasoning_required": True,
        "notes": "Requires classification (which drugs are 1st vs 2nd gen), comparative analysis, and synthesis of clinical data. Agent must understand the distinction and find head-to-head or meta-analysis data."
    },

    # =========================================================================
    # AMBIGUOUS QUERY (1 case)
    # Tests how agent handles unclear or overly broad requests
    # =========================================================================

    {
        "id": 10,
        "query": "Find new cancer drugs",
        "difficulty": "ambiguous",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": [],  # Too broad to have specific expectations
        "min_results": 5,
        "success_criteria": "Agent should acknowledge ambiguity, make reasonable assumptions (e.g., focus on recently approved or in late-stage trials), and provide useful results despite vagueness",
        "reasoning_required": True,
        "notes": "Deliberately vague query. Good agent behavior: Ask for clarification OR make explicit assumptions (e.g., 'Interpreting as drugs approved in last 5 years'). Bad agent behavior: Return random cancer drugs without addressing ambiguity."
    },
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_test_case_by_id(test_id: int):
    """Get a specific test case by ID.

    Args:
        test_id: The test case ID

    Returns:
        Test case dictionary or None if not found
    """
    for case in TEST_CASES:
        if case["id"] == test_id:
            return case
    return None


def get_test_cases_by_difficulty(difficulty: str):
    """Get all test cases of a specific difficulty level.

    Args:
        difficulty: One of "easy", "medium", "hard", "ambiguous"

    Returns:
        List of test case dictionaries
    """
    return [case for case in TEST_CASES if case["difficulty"] == difficulty]


def get_test_subset(count: int = 5):
    """Get a subset of test cases for quick evaluation.

    Useful for hyperparameter tuning where we don't want to run all tests.

    Args:
        count: Number of test cases to return

    Returns:
        List of test case dictionaries (diverse selection)
    """
    # Return a mix of difficulties
    easy = get_test_cases_by_difficulty("easy")[:1]
    medium = get_test_cases_by_difficulty("medium")[:3]
    hard = get_test_cases_by_difficulty("hard")[:1]

    return easy + medium + hard


def print_test_cases():
    """Print all test cases in a readable format."""
    print(f"\n{'='*70}")
    print("MEDAGENT TEST CASES")
    print(f"{'='*70}\n")

    for difficulty in ["easy", "medium", "hard", "ambiguous"]:
        cases = get_test_cases_by_difficulty(difficulty)
        if cases:
            print(f"\n{difficulty.upper()} ({len(cases)} cases):")
            print("-" * 70)
            for case in cases:
                print(f"\n  [{case['id']}] {case['query']}")
                print(f"      Expected tools: {', '.join(case['expected_tools'])}")
                if case['expected_drugs']:
                    print(f"      Expected drugs: {', '.join(case['expected_drugs'][:3])}...")
                print(f"      Success: {case['success_criteria'][:80]}...")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    # Print all test cases
    print_test_cases()

    # Show statistics
    print("\nSTATISTICS:")
    print(f"Total test cases: {len(TEST_CASES)}")
    print(f"Easy: {len(get_test_cases_by_difficulty('easy'))}")
    print(f"Medium: {len(get_test_cases_by_difficulty('medium'))}")
    print(f"Hard: {len(get_test_cases_by_difficulty('hard'))}")
    print(f"Ambiguous: {len(get_test_cases_by_difficulty('ambiguous'))}")

    # Show test subset
    subset = get_test_subset()
    print(f"\nTest subset for tuning ({len(subset)} cases):")
    for case in subset:
        print(f"  - [{case['id']}] {case['query']} ({case['difficulty']})")
