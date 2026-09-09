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

    # =========================================================================
    # PHASE 2 EXPANSION (ids 11-60, 50 additional cases)
    #
    # Added to give the evaluation framework enough scale for percentage
    # metrics to mean something (10 cases could not substantiate any
    # meaningful "X% task completion" claim). Organized the same way as the
    # original 10 - easy/medium/hard/ambiguous - with deliberate coverage of:
    #   - each tool individually (single-tool queries per tool, not just
    #     multi-tool combos, so tool_precision has real single-tool signal)
    #   - two-tool and three-tool combinations
    #   - queries broad/complex enough to plausibly trigger the
    #     self-reflection loop (needs_more_research) - flagged in "notes"
    #     where that's the specific intent, though the actual decision is
    #     always the live LLM's, not something a test case can force
    # =========================================================================

    # -------------------------------------------------------------------
    # EASY (15 new cases, ids 11-25) - single-tool, single-hop
    # -------------------------------------------------------------------

    {
        "id": 11,
        "query": "What is the mechanism of action of metformin in type 2 diabetes?",
        "difficulty": "easy",
        "expected_tools": ["pubmed"],
        "expected_drugs": ["Metformin"],
        "min_results": 3,
        "success_criteria": "Should describe AMPK activation / hepatic glucose output reduction, grounded in literature",
        "reasoning_required": False,
        "notes": "Pure literature/mechanism query - pubmed-only single-tool coverage."
    },
    {
        "id": 12,
        "query": "What is known about the pathophysiology of long COVID?",
        "difficulty": "easy",
        "expected_tools": ["pubmed"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Should summarize literature findings on persistent symptoms and proposed mechanisms",
        "reasoning_required": False,
        "notes": "Pubmed-only literature review query, no drug/trial component expected."
    },
    {
        "id": 13,
        "query": "What clinical trials are currently recruiting for Alzheimer's disease?",
        "difficulty": "easy",
        "expected_tools": ["clinical_trials"],
        "expected_drugs": [],
        "min_results": 5,
        "success_criteria": "Should return actively recruiting trials with NCT IDs and brief descriptions",
        "reasoning_required": False,
        "notes": "ClinicalTrials.gov-only single-tool coverage."
    },
    {
        "id": 14,
        "query": "Find completed Phase 3 trials for rheumatoid arthritis biologics",
        "difficulty": "easy",
        "expected_tools": ["clinical_trials"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Should return completed Phase 3 trials with status and intervention details",
        "reasoning_required": False,
        "notes": "ClinicalTrials.gov-only, filtered query (phase + status)."
    },
    {
        "id": 15,
        "query": "Find JAK inhibitors",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Tofacitinib", "Baricitinib", "Ruxolitinib", "Upadacitinib"],
        "min_results": 3,
        "success_criteria": "Should identify major JAK inhibitors from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only target-class query."
    },
    {
        "id": 16,
        "query": "What compounds target the androgen receptor?",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Enzalutamide", "Bicalutamide", "Apalutamide"],
        "min_results": 3,
        "success_criteria": "Should identify androgen receptor-targeting compounds from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only target-based query."
    },
    {
        "id": 17,
        "query": "List approved HMG-CoA reductase inhibitors (statins)",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Atorvastatin", "Simvastatin", "Rosuvastatin", "Pravastatin"],
        "min_results": 3,
        "success_criteria": "Should identify major approved statins from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only, well-documented drug class - should be a very reliable case."
    },
    {
        "id": 18,
        "query": "Find small molecule inhibitors of BRAF",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Vemurafenib", "Dabrafenib", "Encorafenib"],
        "min_results": 3,
        "success_criteria": "Should identify BRAF inhibitors from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only target query, distinct target class from the existing EGFR/BTK easy cases."
    },
    {
        "id": 19,
        "query": "Find approved ALK inhibitors",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Crizotinib", "Alectinib", "Ceritinib", "Lorlatinib"],
        "min_results": 3,
        "success_criteria": "Should identify ALK inhibitors from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only target query."
    },
    {
        "id": 20,
        "query": "Find VEGF inhibitors approved for macular degeneration",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Ranibizumab", "Aflibercept", "Bevacizumab"],
        "min_results": 2,
        "success_criteria": "Should identify anti-VEGF compounds used in ophthalmology from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only, non-oncology indication for variety (most other target queries skew cancer)."
    },
    {
        "id": 21,
        "query": "Find approved TNF-alpha inhibitors",
        "difficulty": "easy",
        "expected_tools": ["chembl"],
        "expected_drugs": ["Adalimumab", "Etanercept", "Infliximab"],
        "min_results": 3,
        "success_criteria": "Should identify major anti-TNF biologics from ChEMBL",
        "reasoning_required": False,
        "notes": "ChEMBL-only target-class query, autoimmune/inflammatory space."
    },
    {
        "id": 22,
        "query": "What is ibrutinib used for?",
        "difficulty": "easy",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Ibrutinib"],
        "min_results": 4,
        "success_criteria": "Should identify ibrutinib as a BTK inhibitor used in B-cell malignancies (e.g. CLL, mantle cell lymphoma)",
        "reasoning_required": False,
        "notes": "Single-compound indication query, mirrors the existing pembrolizumab easy case with a different drug class."
    },
    {
        "id": 23,
        "query": "What are the known resistance mechanisms to imatinib in chronic myeloid leukemia?",
        "difficulty": "easy",
        "expected_tools": ["pubmed"],
        "expected_drugs": ["Imatinib"],
        "min_results": 3,
        "success_criteria": "Should describe BCR-ABL kinase domain mutations and other resistance mechanisms from literature",
        "reasoning_required": False,
        "notes": "Pubmed-only mechanism/resistance literature query."
    },
    {
        "id": 24,
        "query": "Review the role of the gut microbiome in inflammatory bowel disease treatment",
        "difficulty": "easy",
        "expected_tools": ["pubmed"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Should summarize literature on microbiome-IBD treatment connections",
        "reasoning_required": False,
        "notes": "Pubmed-only literature review, no specific drug expected."
    },
    {
        "id": 25,
        "query": "What is the status of trials for CAR-T cell therapy in multiple myeloma?",
        "difficulty": "easy",
        "expected_tools": ["clinical_trials"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Should return CAR-T trials for multiple myeloma with phase/status information",
        "reasoning_required": False,
        "notes": "ClinicalTrials.gov-only, cell-therapy modality for variety beyond small molecules/biologics."
    },

    # -------------------------------------------------------------------
    # MEDIUM (20 new cases, ids 26-45) - multi-tool cross-referencing
    # -------------------------------------------------------------------

    {
        "id": 26,
        "query": "What PARP inhibitors are used for BRCA-mutant ovarian cancer?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials"],
        "expected_drugs": ["Olaparib", "Niraparib", "Rucaparib"],
        "min_results": 3,
        "success_criteria": "Should identify PARP inhibitors and cross-reference with BRCA-mutant ovarian cancer trials",
        "reasoning_required": True,
        "notes": "Two-tool combo: chembl (find PARP inhibitors) + clinical_trials (verify indication)."
    },
    {
        "id": 27,
        "query": "Find SGLT2 inhibitors and their trial status for heart failure",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials"],
        "expected_drugs": ["Dapagliflozin", "Empagliflozin", "Canagliflozin"],
        "min_results": 3,
        "success_criteria": "Should identify SGLT2 inhibitors and find heart failure trial evidence (a repurposed indication beyond diabetes)",
        "reasoning_required": True,
        "notes": "Cross-referencing a diabetes drug class against a non-diabetes indication."
    },
    {
        "id": 28,
        "query": "What is the evidence for metformin in cancer prevention?",
        "difficulty": "medium",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Metformin"],
        "min_results": 3,
        "success_criteria": "Should find literature and trials investigating metformin's anti-cancer/chemopreventive effects",
        "reasoning_required": True,
        "notes": "Repurposing question requiring literature + trials cross-reference, no chembl needed."
    },
    {
        "id": 29,
        "query": "What GLP-1 receptor agonists are approved for obesity?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "pubmed"],
        "expected_drugs": ["Semaglutide", "Liraglutide", "Tirzepatide"],
        "min_results": 3,
        "success_criteria": "Should identify GLP-1 agonists approved for weight management with supporting literature",
        "reasoning_required": True,
        "notes": "chembl + pubmed combo, high-profile drug class."
    },
    {
        "id": 30,
        "query": "Find trials of anti-CD20 antibodies for multiple sclerosis",
        "difficulty": "medium",
        "expected_tools": ["clinical_trials", "pubmed"],
        "expected_drugs": ["Ocrelizumab", "Rituximab", "Ofatumumab"],
        "min_results": 3,
        "success_criteria": "Should find MS trials for anti-CD20 therapies with supporting mechanism literature",
        "reasoning_required": True,
        "notes": "clinical_trials + pubmed combo, no chembl needed (target/compound identity is given in the query)."
    },
    {
        "id": 31,
        "query": "What are the cardiovascular risks associated with COX-2 inhibitors?",
        "difficulty": "medium",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Celecoxib", "Rofecoxib"],
        "min_results": 3,
        "success_criteria": "Should find literature and trial evidence on cardiovascular safety signals for COX-2 inhibitors",
        "reasoning_required": True,
        "notes": "Safety-signal question (like rofecoxib's withdrawal) - literature + trials cross-reference."
    },
    {
        "id": 32,
        "query": "Which mTOR inhibitors are approved for renal cell carcinoma and what trials support their use?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Everolimus", "Temsirolimus"],
        "min_results": 4,
        "success_criteria": "Should identify mTOR inhibitors, their RCC trial history, and supporting literature",
        "reasoning_required": True,
        "notes": "Three-tool combo requiring find-then-verify-then-explain chain."
    },
    {
        "id": 33,
        "query": "Compare efficacy of anti-TNF biologics for psoriatic arthritis",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Adalimumab", "Etanercept", "Infliximab", "Certolizumab"],
        "min_results": 4,
        "success_criteria": "Should identify anti-TNF biologics and compare trial-based efficacy evidence for psoriatic arthritis",
        "reasoning_required": True,
        "notes": "Three-tool combo requiring comparative synthesis across compounds."
    },
    {
        "id": 34,
        "query": "What are the approved treatments for chronic hepatitis C and their trial history?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Sofosbuvir", "Ledipasvir", "Velpatasvir"],
        "min_results": 4,
        "success_criteria": "Should identify direct-acting antivirals for hepatitis C with trial and literature support",
        "reasoning_required": True,
        "notes": "Three-tool combo, well-documented drug class (DAAs) with strong trial history."
    },
    {
        "id": 35,
        "query": "Find HER2-targeted therapies for breast cancer and their clinical development status",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Trastuzumab", "Pertuzumab", "Trastuzumab emtansine"],
        "min_results": 4,
        "success_criteria": "Should identify HER2-targeted agents with trial status and literature support",
        "reasoning_required": True,
        "notes": "Three-tool combo, distinct target class (HER2) from the existing EGFR/BRAF/BTK cases."
    },
    {
        "id": 36,
        "query": "What mAChR agonists are studied for Alzheimer's disease?",
        "difficulty": "medium",
        "expected_tools": ["pubmed", "chembl"],
        "expected_drugs": [],
        "min_results": 2,
        "success_criteria": "Should identify muscarinic receptor agonists under investigation with supporting literature",
        "reasoning_required": True,
        "notes": "pubmed + chembl combo, exploratory target class where clinical_trials data may be sparse - tests graceful handling of a less mature research area."
    },
    {
        "id": 37,
        "query": "Find approved treatments for cystic fibrosis targeting CFTR",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials"],
        "expected_drugs": ["Ivacaftor", "Lumacaftor", "Elexacaftor"],
        "min_results": 3,
        "success_criteria": "Should identify CFTR modulators and their approval/trial history",
        "reasoning_required": True,
        "notes": "chembl + clinical_trials combo, rare/genetic disease space for variety."
    },
    {
        "id": 38,
        "query": "What antibody-drug conjugates are approved for breast cancer and what trials led to approval?",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Trastuzumab emtansine", "Trastuzumab deruxtecan", "Sacituzumab govitecan"],
        "min_results": 3,
        "success_criteria": "Should identify ADCs and their pivotal trial evidence",
        "reasoning_required": True,
        "notes": "Three-tool combo, newer drug modality (ADCs) for variety."
    },
    {
        "id": 39,
        "query": "Find bispecific antibodies in clinical trials for hematologic malignancies",
        "difficulty": "medium",
        "expected_tools": ["clinical_trials", "pubmed"],
        "expected_drugs": ["Blinatumomab", "Mosunetuzumab", "Teclistamab"],
        "min_results": 3,
        "success_criteria": "Should find bispecific antibody trials with supporting literature",
        "reasoning_required": True,
        "notes": "clinical_trials + pubmed combo, emerging modality."
    },
    {
        "id": 40,
        "query": "What is the trial landscape for gene therapies in hemophilia?",
        "difficulty": "medium",
        "expected_tools": ["clinical_trials", "chembl"],
        "expected_drugs": [],
        "min_results": 2,
        "success_criteria": "Should identify gene therapy trials for hemophilia A/B",
        "reasoning_required": True,
        "notes": "clinical_trials + chembl combo, gene therapy modality likely to strain chembl's small-molecule-oriented data - useful edge case."
    },
    {
        "id": 41,
        "query": "Find approved treatments for pulmonary arterial hypertension and their targets",
        "difficulty": "medium",
        "expected_tools": ["chembl", "clinical_trials"],
        "expected_drugs": ["Bosentan", "Sildenafil", "Ambrisentan", "Macitentan"],
        "min_results": 3,
        "success_criteria": "Should identify PAH treatments across drug classes (endothelin antagonists, PDE5 inhibitors) with trial support",
        "reasoning_required": True,
        "notes": "chembl + clinical_trials combo, rare cardiopulmonary disease for variety."
    },
    {
        "id": 42,
        "query": "What SSRIs are studied for treatment-resistant depression in recent trials?",
        "difficulty": "medium",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Fluoxetine", "Escitalopram", "Sertraline"],
        "min_results": 3,
        "success_criteria": "Should find recent trial and literature evidence on SSRIs in treatment-resistant depression",
        "reasoning_required": True,
        "notes": "pubmed + clinical_trials combo, psychiatry indication for variety."
    },
    {
        "id": 43,
        "query": "Find approved treatments for chronic myeloid leukemia and compare their targets",
        "difficulty": "medium",
        "expected_tools": ["chembl", "pubmed"],
        "expected_drugs": ["Imatinib", "Dasatinib", "Nilotinib", "Bosutinib"],
        "min_results": 4,
        "success_criteria": "Should identify BCR-ABL inhibitors approved for CML and compare their mechanisms via literature",
        "reasoning_required": True,
        "notes": "chembl + pubmed combo requiring comparative synthesis across generations of the same drug class."
    },
    {
        "id": 44,
        "query": "What is the evidence for statins in reducing all-cause mortality?",
        "difficulty": "medium",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Atorvastatin", "Simvastatin"],
        "min_results": 3,
        "success_criteria": "Should synthesize trial and literature evidence on statin mortality benefit",
        "reasoning_required": True,
        "notes": "pubmed + clinical_trials combo, large well-studied evidence base (should be a reliable case)."
    },
    {
        "id": 45,
        "query": "What trials support use of semaglutide for cardiovascular risk reduction?",
        "difficulty": "medium",
        "expected_tools": ["clinical_trials", "pubmed"],
        "expected_drugs": ["Semaglutide"],
        "min_results": 2,
        "success_criteria": "Should find cardiovascular outcome trials for semaglutide with supporting literature",
        "reasoning_required": True,
        "notes": "clinical_trials + pubmed combo, single-compound repurposing/label-expansion question."
    },

    # -------------------------------------------------------------------
    # HARD (10 new cases, ids 46-55) - complex reasoning, nuanced filtering
    # -------------------------------------------------------------------

    {
        "id": 46,
        "query": "Why did several BACE inhibitors fail in Alzheimer's clinical trials?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": [],
        "min_results": 2,
        "success_criteria": "Should identify failed BACE inhibitor trials and explain causality (e.g. lack of efficacy, worsened cognition)",
        "reasoning_required": True,
        "notes": "Requires identifying failures AND causal explanation - likely to need multiple research iterations (good self-reflection-loop candidate)."
    },
    {
        "id": 47,
        "query": "Compare the safety profiles of first-generation vs second-generation antihistamines",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "chembl"],
        "expected_drugs": ["Diphenhydramine", "Loratadine", "Cetirizine", "Fexofenadine"],
        "min_results": 4,
        "success_criteria": "Should classify drugs by generation and compare sedation/anticholinergic safety data",
        "reasoning_required": True,
        "notes": "Requires classification (generation) plus comparative safety synthesis, mirrors the existing EGFR-TKI-generation hard case."
    },
    {
        "id": 48,
        "query": "What explains variable response to checkpoint inhibitor therapy across tumor types?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Pembrolizumab", "Nivolumab"],
        "min_results": 3,
        "success_criteria": "Should discuss biomarkers (e.g. PD-L1 expression, tumor mutational burden, microsatellite instability) driving differential response",
        "reasoning_required": True,
        "notes": "Very challenging, exploratory causal/mechanistic question - good self-reflection-loop candidate given its breadth."
    },
    {
        "id": 49,
        "query": "Assess the evidence for repurposing metformin as an anti-aging intervention",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Metformin"],
        "min_results": 2,
        "success_criteria": "Should synthesize preclinical rationale and any human trial evidence (e.g. TAME trial) while being honest about how preliminary this is",
        "reasoning_required": True,
        "notes": "Tests honest handling of a speculative/early-stage research area - agent should flag uncertainty rather than overstate evidence."
    },
    {
        "id": 50,
        "query": "Why do some EGFR-mutant lung cancers develop resistance to osimertinib?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": ["Osimertinib"],
        "min_results": 2,
        "success_criteria": "Should identify resistance mechanisms (e.g. C797S mutation, MET amplification) from literature",
        "reasoning_required": True,
        "notes": "Deep mechanistic/causal question requiring literature synthesis, complements the existing EGFR-TKI comparative hard case."
    },
    {
        "id": 51,
        "query": "Compare the mechanisms and clinical outcomes of CAR-T therapies targeting CD19 vs BCMA",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials", "chembl"],
        "expected_drugs": ["Tisagenlecleucel", "Axicabtagene ciloleucel", "Idecabtagene vicleucel"],
        "min_results": 3,
        "success_criteria": "Should distinguish target-specific CAR-T products and compare outcomes/indications (lymphoma/leukemia vs myeloma)",
        "reasoning_required": True,
        "notes": "Requires classification by target antigen plus comparative outcome synthesis across a cell-therapy modality chembl handles poorly - tests graceful degradation."
    },
    {
        "id": 52,
        "query": "Find kinase inhibitors originally developed for cancer that are now being tested for autoimmune disease",
        "difficulty": "hard",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Tofacitinib", "Baricitinib", "Ibrutinib"],
        "min_results": 3,
        "success_criteria": "Should identify repurposed kinase inhibitors and cross-reference original vs new indication trials",
        "reasoning_required": True,
        "notes": "Requires two-step reasoning: identify original oncology use, then find unrelated autoimmune trials - good self-reflection-loop candidate."
    },
    {
        "id": 53,
        "query": "Find complement inhibitors approved for paroxysmal nocturnal hemoglobinuria and compare their clinical trial evidence",
        "difficulty": "hard",
        "expected_tools": ["chembl", "clinical_trials", "pubmed"],
        "expected_drugs": ["Eculizumab", "Ravulizumab", "Pegcetacoplan"],
        "min_results": 2,
        "success_criteria": "Should identify complement (C5/C3) inhibitors for PNH and compare pivotal trial evidence across generations",
        "reasoning_required": True,
        "notes": "Rare disease with a small number of highly specific compounds - tests precision on a narrow, well-defined space."
    },
    {
        "id": 54,
        "query": "What is the comparative efficacy of first-line vs second-line therapies for metastatic colorectal cancer with KRAS mutations?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials", "chembl"],
        "expected_drugs": ["Bevacizumab", "Cetuximab", "Sotorasib"],
        "min_results": 3,
        "success_criteria": "Should distinguish KRAS-mutant-appropriate regimens from EGFR-antibody therapies (typically ineffective in KRAS-mutant disease) with trial support",
        "reasoning_required": True,
        "notes": "Requires biomarker-aware reasoning (KRAS status changes which drugs are even appropriate) - a genuine nuanced filtering challenge."
    },
    {
        "id": 55,
        "query": "Which small-molecule kinase inhibitors have had black-box warnings added after approval, and why?",
        "difficulty": "hard",
        "expected_tools": ["pubmed", "clinical_trials"],
        "expected_drugs": [],
        "min_results": 2,
        "success_criteria": "Should identify specific post-market safety findings and causal rationale for black-box warnings",
        "reasoning_required": True,
        "notes": "Post-market safety surveillance question - information is scattered and harder to find than pre-approval trial data, good self-reflection-loop candidate."
    },

    # -------------------------------------------------------------------
    # AMBIGUOUS (5 new cases, ids 56-60) - unclear/overly broad requests
    # -------------------------------------------------------------------

    {
        "id": 56,
        "query": "Tell me about diabetes drugs",
        "difficulty": "ambiguous",
        "expected_tools": ["chembl", "pubmed", "clinical_trials"],
        "expected_drugs": [],
        "min_results": 5,
        "success_criteria": "Agent should narrow scope explicitly (e.g. by drug class or type 1 vs type 2) rather than returning an unfocused dump",
        "reasoning_required": True,
        "notes": "Vague, extremely broad disease-area query with no target/indication specificity given."
    },
    {
        "id": 57,
        "query": "What's new in oncology?",
        "difficulty": "ambiguous",
        "expected_tools": ["pubmed", "clinical_trials", "chembl"],
        "expected_drugs": [],
        "min_results": 5,
        "success_criteria": "Agent should make an explicit, reasonable interpretation (e.g. recent approvals or high-activity trial areas) rather than a directionless search",
        "reasoning_required": True,
        "notes": "No disease, target, or drug specified at all - maximally vague, good self-reflection-loop candidate since initial results will likely feel insufficient to answer 'what's new'."
    },
    {
        "id": 58,
        "query": "Find good drugs for pain",
        "difficulty": "ambiguous",
        "expected_tools": ["chembl", "pubmed"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Agent should clarify pain type assumption (e.g. chronic/neuropathic vs acute) rather than returning an arbitrary mix",
        "reasoning_required": True,
        "notes": "'Good' is subjective and pain type is unspecified - tests handling of a value-laden, ambiguous adjective."
    },
    {
        "id": 59,
        "query": "Any updates on Alzheimer's treatment?",
        "difficulty": "ambiguous",
        "expected_tools": ["pubmed", "clinical_trials", "chembl"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Agent should interpret 'updates' as recent literature/trials and say so explicitly rather than returning an undated general summary",
        "reasoning_required": True,
        "notes": "Temporal ambiguity ('updates') on top of an already broad disease area."
    },
    {
        "id": 60,
        "query": "What should I know about biologics?",
        "difficulty": "ambiguous",
        "expected_tools": ["chembl", "pubmed"],
        "expected_drugs": [],
        "min_results": 3,
        "success_criteria": "Agent should narrow 'biologics' to a concrete scope (e.g. a drug class or indication) and say so, rather than a generic textbook answer",
        "reasoning_required": True,
        "notes": "No disease, target, or drug class specified - tests whether the agent grounds an open-ended conceptual question in real retrieved data at all."
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
