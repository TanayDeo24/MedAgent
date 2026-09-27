"""Phase 2 Biomedical NLU package.

Public interface: `understand_query(text) -> ResearchQuery` and
`to_legacy_research_plan(rq) -> dict` (the backward-compatibility adapter
described in `docs/v2/PHASE2_BIOMEDICAL_NLU.md` Section "LangGraph
integration").
"""

import json
import os
from typing import Any, Dict, Optional

from nlu.extractor import ARCHITECTURE_FUNCS
from nlu.schemas import NLUExtractionResult, ResearchQuery, SCHEMA_VERSION  # noqa: F401
from utils.logger import get_logger

logger = get_logger(__name__)

_FROZEN_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "artifacts", "v2", "nlu_frozen_config.json",
)

_frozen_architecture_cache: Optional[str] = None


def _frozen_architecture() -> str:
    """Reads artifacts/v2/nlu_frozen_config.json to decide which candidate
    architecture understand_query() delegates to. Falls back to
    'candidate_a_baseline' (the safest, most conservative choice) with a
    loud warning if the frozen config is missing or unreadable - this
    should never happen after Phase 2 selection is complete, but a
    production import must not crash if it does."""
    global _frozen_architecture_cache
    if _frozen_architecture_cache is not None:
        return _frozen_architecture_cache

    try:
        with open(_FROZEN_CONFIG_PATH) as f:
            config = json.load(f)
        arch = config["selected_architecture"]
        if arch not in ARCHITECTURE_FUNCS:
            raise ValueError(f"Unknown architecture in frozen config: {arch}")
        _frozen_architecture_cache = arch
    except Exception as e:
        logger.warning(
            f"[NLU] Could not load frozen config from {_FROZEN_CONFIG_PATH} "
            f"({e}); defaulting to candidate_a_baseline"
        )
        _frozen_architecture_cache = "candidate_a_baseline"

    return _frozen_architecture_cache


def understand_query_with_result(text: str) -> NLUExtractionResult:
    """Run the frozen, selected NLU architecture on `text` and return the
    full NLUExtractionResult (schema validity, latency, LLM-call count,
    token usage) alongside the ResearchQuery. Use this over
    understand_query() when a caller needs that extraction-process
    metadata (e.g. agent/nodes.py accumulating token usage the same way
    every other node does)."""
    arch = _frozen_architecture()
    fn = ARCHITECTURE_FUNCS[arch]
    return fn(text)


def understand_query(text: str) -> ResearchQuery:
    """Run the frozen, selected NLU architecture on `text` and return a
    validated ResearchQuery. Raises if extraction fails structurally
    (schema_valid=False) - callers (agent/nodes.py's query_analysis_node)
    are responsible for their own fallback behavior on failure, exactly as
    the pre-Phase-2 code already did for its own JSON-parse failures.
    """
    result = understand_query_with_result(text)
    if not result.schema_valid or result.research_query is None:
        raise ValueError(f"NLU extraction failed ({result.architecture}): {result.parse_error}")
    return result.research_query


def to_legacy_research_plan(rq: ResearchQuery) -> Dict[str, Any]:
    """TEMPORARY backward-compatibility adapter.

    Serializes a ResearchQuery into the OLD research_plan dict shape
    (`drug_targets`, `diseases`, `compounds`, `query_type`,
    `key_constraints`, `extracted_keywords`, `confidence`) so
    `query_analysis_node` and everything downstream of it in
    agent/nodes.py keeps working completely unchanged. This function - and
    the old dict shape it produces - is explicitly temporary scaffolding
    for Phase 2 only.

    Phase 3 (docs/v2/PHASE3_TOOL_ORCHESTRATION.md) note: the node that used
    to consume this dict for tool *selection* (`planning_node`) was removed
    in the Step 34 integration - the frozen Candidate B architecture
    selects tools directly from raw `state["query"]` text via Cerebras
    native tool calling, not from this adapter's output (see
    docs/v2/PHASE3_WINNER_SELECTION.md Section 2 on why Candidate B is
    measured/driven from raw text). `research_plan` (this function's
    output) is still stored in state and still read by `synthesis_node`/
    `verification_node`'s prompts as narrative context, and by
    `tool_orchestration_node` only to append its own "orchestration" trace
    block - it is no longer on the tool-selection path. A future phase
    that redesigns that narrative-context contract should remove this
    adapter rather than extend it.
    """
    drug_targets = [e.surface_form for e in rq.entities if e.entity_type.value in ("gene", "protein", "target")]
    diseases = [e.surface_form for e in rq.entities if e.entity_type.value == "disease"]
    compounds = [e.surface_form for e in rq.entities if e.entity_type.value in ("compound", "intervention")]

    # Old schema supports exactly one query_type string; take the
    # highest-confidence / first intent when multi-label, and map onto the
    # closest legacy category. This is a lossy, intentionally temporary
    # projection - see docstring.
    _INTENT_TO_OLD_TYPE = {
        "A_literature_evidence": "literature_review",
        "B_clinical_trial_landscape": "clinical_trial_search",
        "C_compound_target": "drug_target_search",
        "D_cross_source_synthesis": "general_research",
        "E_multi_hop_research": "general_research",
        "F_mechanism": "compound_information",
        "G_constraint_heavy": "clinical_trial_search",
        # H_insufficient_evidence intentionally absent - removed from the
        # query-time IntentClass enum in Phase 2 closure (nlu/taxonomy.py);
        # rq.intent can no longer contain it. See taxonomy.py docstring.
        "I_ambiguous": "general_research",
    }
    query_type = _INTENT_TO_OLD_TYPE.get(rq.intent[0].value, "general_research") if rq.intent else "general_research"

    key_constraints = [f"{field}: {value}" for field, value in rq.constraints.as_pairs()]

    extracted_keywords = list(dict.fromkeys(drug_targets + diseases + compounds))  # dedup, preserve order

    return {
        "drug_targets": drug_targets,
        "diseases": diseases,
        "compounds": compounds,
        "query_type": query_type,
        "key_constraints": key_constraints,
        "extracted_keywords": extracted_keywords,
        "confidence": rq.extraction_confidence,
    }
