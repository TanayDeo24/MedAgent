# Phase 2 Architecture - Reasoning Nodes & Tool Integration

## Overview

Phase 2 transforms MedAgent from a basic infrastructure (Phase 1) into a **truly autonomous research agent**. The agent now makes its own decisions about:
- What information to extract from queries
- Which tools to use and in what order
- Whether research is complete or more investigation is needed
- How to synthesize findings from multiple sources
- What to include in the final report

This is NOT just an LLM wrapper - it's a **real agentic system** with autonomous decision-making, self-reflection, and iterative improvement.

## What Phase 2 Accomplishes

✅ **6 LLM-Powered Reasoning Nodes**: Each node uses the LLM to make autonomous decisions
✅ **Dynamic Tool Selection**: Agent chooses which APIs to call based on query analysis
✅ **Real API Integration**: Actually calls PubMed, ClinicalTrials, ChEMBL with optimized queries
✅ **Cross-Reference Synthesis**: Combines findings from multiple sources intelligently
✅ **Self-Reflection Loop**: Agent evaluates its own work and decides when to stop
✅ **Professional Reports**: Generates well-structured markdown with citations
✅ **Comprehensive Testing**: 7 tests validating all capabilities

## Architecture Diagram

```
User Query: "Find EGFR inhibitors for lung cancer"
                │
                ▼
┌───────────────────────────────────────────────────────────────┐
│                    MEDAGENT WORKFLOW                          │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. QUERY ANALYSIS NODE                              │    │
│  │    LLM extracts:                                     │    │
│  │    - Targets: ["EGFR"]                               │    │
│  │    - Diseases: ["lung cancer"]                       │    │
│  │    - Type: "drug_target_search"                      │    │
│  │    - Confidence: 0.85                                │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                      │
│                        ▼                                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 2. PLANNING NODE                                     │    │
│  │    LLM creates strategy:                             │    │
│  │    - Tool 1: ChEMBL (find compounds)                 │    │
│  │    - Tool 2: ClinicalTrials (find trials)            │    │
│  │    - Tool 3: PubMed (find mechanisms)                │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                      │
│                        ▼                                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 3. TOOL EXECUTION NODE                               │    │
│  │    For each tool:                                    │    │
│  │      - LLM generates optimized query                 │    │
│  │      - Call actual API                               │    │
│  │      - Store results                                 │    │
│  │                                                       │    │
│  │    ChEMBL → 15 compounds                             │    │
│  │    ClinicalTrials → 8 trials                         │    │
│  │    PubMed → 20 papers                                │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                      │
│                        ▼                                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 4. SYNTHESIS NODE                                    │    │
│  │    LLM combines findings:                            │    │
│  │    - Erlotinib (ChEMBL) → NCT123 (trials)           │    │
│  │    - Gefitinib mentioned in 5 papers                 │    │
│  │    - Cross-references validated                      │    │
│  │    - Gaps identified                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                      │
│                        ▼                                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 5. VERIFICATION NODE (Self-Reflection)               │    │
│  │    LLM evaluates:                                    │    │
│  │    - Query coverage: 0.75                            │    │
│  │    - Evidence quality: 0.80                          │    │
│  │    - Completeness: 0.65                              │    │
│  │    - Overall confidence: 0.73                        │    │
│  │                                                       │    │
│  │    Decision: CONTINUE (need more clinical data)      │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                      │
│              ┌─────────┴──────────┐                          │
│              ▼                    ▼                           │
│    needs_more_info=true   needs_more_info=false              │
│              │                    │                           │
│              │                    │                           │
│    ┌─────────┘                    │                           │
│    │ (Loop back to step 3)        │                           │
│    │                              │                           │
│    ▼                              ▼                           │
│  TOOL EXECUTION           ┌──────────────────────────────┐   │
│  (2nd iteration)          │ 6. REPORT GENERATION NODE    │   │
│                           │    LLM creates:               │   │
│  New tools called         │    - Executive summary        │   │
│  based on gaps            │    - Key findings             │   │
│                           │    - Detailed analysis        │   │
│    │                      │    - Tables & citations       │   │
│    │                      │    - Knowledge gaps           │   │
│    ▼                      └──────────────────────────────┘   │
│  SYNTHESIS                                │                   │
│  (2nd iteration)                          │                   │
│    │                                      ▼                   │
│    ▼                              ┌──────────────────┐        │
│  VERIFICATION                     │ FINAL REPORT     │        │
│    │                              │ (Markdown)       │        │
│    │ needs_more_info=false        └──────────────────┘        │
│    │                                                           │
│    ▼                                                           │
│  REPORT                                                        │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

## Node Descriptions

### Node 1: Query Analysis

**Purpose**: Extract structured information from the user's natural language query.

**LLM Task**: Parse query and return JSON with:
- `drug_targets`: Proteins, genes, pathways mentioned
- `diseases`: Medical conditions
- `compounds`: Specific drugs
- `query_type`: Classification (drug_target_search, disease_treatment_search, etc.)
- `key_constraints`: Requirements like "FDA approved", "phase 3 trials"
- `confidence`: Self-assessed confidence in extraction

**Example**:
```
Input: "Find EGFR inhibitors for lung cancer in phase 3 trials"

Output (JSON):
{
  "drug_targets": ["EGFR"],
  "diseases": ["lung cancer"],
  "compounds": [],
  "query_type": "clinical_trial_search",
  "key_constraints": ["phase 3 trials"],
  "extracted_keywords": ["EGFR", "inhibitors", "lung cancer", "phase 3"],
  "confidence": 0.90
}
```

**Why This Matters**: The agent can't research what it doesn't understand. This structured extraction guides all downstream decisions.

### Node 2: Planning

**Purpose**: Autonomously decide which tools to use and in what order.

**LLM Task**: Given the query analysis and available tools, create a research strategy:
- Select 1-3 tools (PubMed, ClinicalTrials, ChEMBL)
- Order them by priority
- Explain rationale for each tool
- Estimate complexity

**Decision Logic**:
- Drug target queries → ChEMBL first (find compounds), then trials, then literature
- Disease queries → ClinicalTrials first (find treatments), then literature, then compounds
- Compound queries → ChEMBL first (get details), then trials, then papers
- Literature reviews → PubMed only

**Example**:
```json
{
  "research_strategy": "Find EGFR inhibitor compounds in ChEMBL, then validate with clinical trials",
  "tools_to_use": [
    {
      "tool": "chembl",
      "priority": 1,
      "rationale": "Find compounds targeting EGFR",
      "expected_output": "List of EGFR inhibitor compounds with approval status"
    },
    {
      "tool": "clinical_trials",
      "priority": 2,
      "rationale": "Find phase 3 trials for these compounds in lung cancer",
      "expected_output": "Active trials with NCT IDs and status"
    }
  ],
  "estimated_complexity": "moderate"
}
```

**Why This Matters**: The agent autonomously decides its research path - no hardcoded rules.

### Node 3: Tool Execution

**Purpose**: Call the actual APIs with LLM-optimized queries.

**How It Works**:
1. For each tool in the plan:
   - LLM generates tool-specific query parameters
   - Call the actual API (PubMed/ClinicalTrials/ChEMBL)
   - Store results in `tool_results`
   - Log call in `tool_call_history`
2. Increment step counter

**LLM Query Generation**: The LLM converts the original query into tool-specific search terms:

```
Original: "Find EGFR inhibitors for lung cancer"
Tool: pubmed

LLM generates:
{
  "tool": "pubmed",
  "parameters": {
    "query": "EGFR inhibitors AND lung cancer AND clinical",
    "max_results": 20,
    "years_back": 5
  },
  "search_rationale": "Focus on recent clinical research combining both target and disease"
}
```

**Real API Calls**: This node actually calls the live APIs - no mocking. Results are real data from:
- PubMed E-utilities (papers, abstracts, PMIDs)
- ClinicalTrials.gov API v2 (trials, status, NCT IDs)
- ChEMBL REST API (compounds, targets, phases)

**Error Handling**: If one tool fails, others continue. Errors logged but don't crash the agent.

### Node 4: Synthesis

**Purpose**: Combine findings from multiple tools and identify cross-references.

**LLM Task**: Given results from all tools, synthesize findings:
- Extract key facts from each tool
- Find connections between tools (e.g., compound in ChEMBL also in trial from ClinicalTrials)
- Note patterns and repeated information
- Flag inconsistencies
- Identify gaps in knowledge

**Example**:
```json
{
  "key_findings": [
    {
      "finding": "Erlotinib is an FDA-approved EGFR inhibitor (Phase 4)",
      "sources": ["chembl", "clinical_trials"],
      "evidence_strength": "strong"
    },
    {
      "finding": "Multiple phase 3 trials for erlotinib in NSCLC completed",
      "sources": ["clinical_trials", "pubmed"],
      "evidence_strength": "strong"
    }
  ],
  "cross_references": [
    {
      "connection": "Erlotinib (ChEMBL: CHEMBL1173) appears in 3 active trials (ClinicalTrials)",
      "tools_involved": ["chembl", "clinical_trials"],
      "significance": "Validates current clinical use"
    }
  ],
  "identified_gaps": [
    "No information on adverse effects found",
    "Missing biomarker data for patient selection"
  ],
  "overall_summary": "Found 5 FDA-approved EGFR inhibitors with active clinical trials...",
  "confidence_in_synthesis": 0.78
}
```

**Critical Rule**: NO HALLUCINATION. The LLM can ONLY synthesize information present in tool results.

### Node 5: Verification (Self-Reflection)

**Purpose**: The agent evaluates its own work and decides whether to continue or stop.

This is the **KEY NODE** that makes the system autonomous. The LLM performs meta-cognition:

**LLM Task**: Evaluate the research on 4 dimensions:
1. **Query Coverage** (0-1): Does research answer the user's question?
2. **Evidence Quality** (0-1): Are findings well-supported by multiple sources?
3. **Completeness** (0-1): Are there significant gaps?
4. **Overall Confidence** (0-1): Aggregate score

**Decision Logic**:
- Continue if: coverage < 0.7 OR confidence < 0.6 OR major gaps identified AND iterations remain
- Stop if: coverage ≥ 0.8 OR confidence ≥ 0.7 OR no iterations remaining

**Example**:
```json
{
  "query_coverage_score": 0.65,
  "evidence_quality_score": 0.80,
  "completeness_score": 0.60,
  "overall_confidence": 0.68,
  "needs_more_research": true,
  "reasoning": "Coverage is moderate but completeness is low - missing clinical efficacy data",
  "identified_gaps": [
    "No information on response rates",
    "Missing comparison between inhibitors"
  ],
  "next_steps": {
    "tools_to_call": ["pubmed"],
    "new_queries": ["EGFR inhibitor response rates lung cancer"],
    "rationale": "Need more clinical outcome data from literature"
  }
}
```

**Why This Matters**: The agent decides for itself when it has enough information. This creates a self-directed learning loop.

### Node 6: Report Generation

**Purpose**: Create a professional, well-structured markdown research report.

**LLM Task**: Given all synthesized findings and tool results, generate:
- Executive summary (2-3 sentences)
- Key findings organized by category
- Detailed analysis with cross-references
- Tables for compounds/trials (if applicable)
- Clinical evidence section (if applicable)
- Knowledge gaps & limitations
- Full references with PubMed IDs, NCT numbers, ChEMBL IDs

**Report Structure**:
```markdown
# Research Report: [Query Topic]

## Executive Summary
[2-3 sentence summary with direct answer]

## Key Findings

### 1. [Category 1 - e.g., "Approved Drugs"]
- Finding 1 (PubMed, ChEMBL)
- Finding 2 (ClinicalTrials)

### 2. [Category 2 - e.g., "Clinical Trials"]
- Finding 1
- Finding 2

## Detailed Analysis

### [Subsection 1]
[Narrative explanation with context and cross-references]

### [Subsection 2]
[More detail]

## Notable Compounds (if applicable)

| Compound | Target | Status | Source |
|----------|--------|--------|--------|
| Erlotinib | EGFR | Phase 4 | ChEMBL |

## Clinical Evidence (if applicable)

- **Trial NCT12345**: Description
- **Trial NCT67890**: Description

## Knowledge Gaps & Limitations

- What wasn't found
- Limitations
- Suggestions for further research

## References

[1] PubMed - PMID: 12345
[2] ClinicalTrials.gov - NCT12345
[3] ChEMBL - CHEMBL1173
```

**Grounding Requirement**: Every claim must be traceable to tool results. Citations are mandatory.

## LangGraph Flow

### Complete Flow Diagram

```
START
  ↓
query_analysis (extract structured info)
  ↓
planning (select tools and strategy)
  ↓
tool_execution (call APIs with optimized queries)
  ↓
synthesis (combine and cross-reference)
  ↓
verification (self-reflect)
  ↓
[DECISION POINT: should_continue_research()]
  │
  ├─→ "continue" (needs_more_info=true AND iterations remain)
  │     │
  │     └─→ tool_execution (2nd iteration with new tools/queries)
  │           ↓
  │         synthesis (2nd iteration)
  │           ↓
  │         verification (2nd iteration)
  │           ↓
  │         [DECISION POINT again...]
  │
  └─→ "report" (needs_more_info=false OR max iterations)
        ↓
      report_generation
        ↓
      END
```

### Conditional Routing Logic

The `should_continue_research()` function implements the decision:

```python
def should_continue_research(state: AgentState) -> str:
    needs_more = state.get("needs_more_info", False)
    current_step = state.get("current_step", 0)
    max_iterations = state.get("max_iterations", 10)

    if needs_more and current_step < max_iterations:
        return "continue"  # Loop back to tool_execution
    else:
        return "report"    # Generate final report
```

This creates a **self-directed learning loop** where the agent iteratively improves its understanding until confident or out of iterations.

## System Prompts

All 6 nodes use carefully engineered system prompts that:
1. Define the node's specific task
2. Specify expected output format (JSON for nodes 1-5, markdown for node 6)
3. Provide examples and guidelines
4. Emphasize grounding in data (no hallucination)
5. Include template variables for dynamic content

See [agent/prompts.py](../agent/prompts.py) for full prompts.

**Key Principles**:
- **Specificity**: Each prompt is highly specific to its node's task
- **Structure**: All prompts (except report) must return valid JSON
- **Examples**: Show the LLM exactly what format to use
- **Grounding**: Repeatedly emphasize: only use information from tool results
- **Self-awareness**: Prompts ask LLM to acknowledge limitations and gaps

## Tool Integration

### How Tools Are Called

1. **Planning Node** decides which tools to use
2. **Tool Execution Node**:
   - For each tool, LLM generates query via `TOOL_QUERY_GENERATION_PROMPT`
   - Instantiate tool: `PubMedTool()`, `ClinicalTrialsTool()`, or `ChEMBLTool()`
   - Call tool method with parameters
   - Store result in `state["tool_results"][tool_name]`
   - Log call in `state["tool_call_history"]`

### Tool-Specific Query Generation

The LLM translates the original query into tool-optimized parameters:

**PubMed**:
```python
{
  "query": "EGFR inhibitors AND lung cancer AND (clinical OR trial)",
  "max_results": 20,
  "years_back": 5
}
```

**ClinicalTrials**:
```python
{
  "query": "EGFR inhibitor",
  "condition": "lung cancer",
  "max_results": 20,
  "status": "recruiting"
}
```

**ChEMBL**:
```python
{
  "query": "EGFR",
  "query_type": "target",
  "max_results": 20
}
```

### Result Storage Format

All tool results follow the `ToolResult` dataclass:
```python
@dataclass
class ToolResult:
    success: bool
    data: List[Dict]  # Actual results
    metadata: Dict    # Timing, caching, etc.
    error: Optional[str]
```

Results are stored in `state["tool_results"]` as:
```python
{
  "pubmed": [
    {"title": "...", "pmid": "...", "abstract": "...", "authors": "..."},
    ...
  ],
  "clinical_trials": [
    {"title": "...", "nct_id": "...", "status": "...", "conditions": [...]}
    ...
  ],
  "chembl": [
    {"pref_name": "...", "molecule_chembl_id": "...", "max_phase": 4, ...},
    ...
  ]
}
```

## Self-Reflection Loop

The self-reflection loop is what makes MedAgent **truly autonomous**. Here's how it works:

### Iteration 1

1. Query Analysis: Extract targets/diseases
2. Planning: Select tools
3. Tool Execution: Call APIs (get 43 results)
4. Synthesis: Combine findings
5. Verification: Evaluate
   - Coverage: 0.65 (moderate)
   - Confidence: 0.62
   - **Decision: CONTINUE** (need more clinical data)

### Iteration 2

3. Tool Execution: Call PubMed again with refined query for clinical outcomes
4. Synthesis: Integrate new papers with existing findings
5. Verification: Re-evaluate
   - Coverage: 0.85 (good)
   - Confidence: 0.81
   - **Decision: STOP** (sufficient information)

6. Report Generation: Create final report

### Why This Works

- Agent learns from its own gaps
- Iteratively refines queries
- Stops when confident (not when told to)
- Can run 1-10+ iterations depending on complexity

## Testing Strategy

Phase 2 includes 7 comprehensive tests:

### 1. Query Analysis Test
- Verifies LLM extracts structured info
- Checks JSON validity
- Validates field presence

### 2. Planning Test
- Verifies tool selection logic
- Checks strategy reasoning
- Validates tool priority ordering

### 3. Tool Execution Test
- Verifies real API calls
- Checks result storage
- Validates error handling

### 4. Synthesis Test
- Verifies cross-referencing
- Checks finding extraction
- Validates gap identification

### 5. Verification Test
- Verifies self-reflection scores
- Checks decision logic
- Validates needs_more_info flag

### 6. Report Generation Test
- Verifies markdown format
- Checks citation extraction
- Validates report structure

### 7. End-to-End Test
- Verifies complete workflow
- Checks all nodes execute
- Validates final report quality
- Tests with real query and real APIs

Run tests:
```bash
cd ~/Documents/MedAgent
source venv/bin/activate
python test_phase2.py
```

## Usage Examples

### Basic Usage

```python
from agent.graph import MedAgent

# Create agent
agent = MedAgent(max_iterations=5, temperature=0.3)

# Run query
result = agent.run("What are EGFR inhibitors for lung cancer?")

# Get report
print(result["final_report"])

# Show reasoning
agent.print_reasoning_trace(result, detailed=True)

# Save report
agent.save_report(result)
```

### Advanced Usage

```python
# Get specific information
trace = agent.get_reasoning_trace(result)
stats = agent.get_tool_usage_stats(result)
citations = agent.get_citations(result)

print(f"Tools used: {stats['tools_called']}")
print(f"Total results: {stats['total_results']}")
print(f"Citations: {len(citations)}")

# Check confidence
confidence = result["confidence_score"]
if confidence < 0.6:
    print("Warning: Low confidence in results")
```

### Configuration Options

```python
# Fast mode (1-2 iterations, higher temperature for creativity)
agent = MedAgent(max_iterations=2, temperature=0.5)

# Thorough mode (many iterations, low temperature for consistency)
agent = MedAgent(max_iterations=10, temperature=0.1)

# Balanced mode (default)
agent = MedAgent(max_iterations=5, temperature=0.3)
```

## Performance Characteristics

### Typical Execution Time

- Simple query (1 iteration): 30-60 seconds
- Complex query (2-3 iterations): 1-3 minutes
- Very complex (4+ iterations): 3-5 minutes

**Bottlenecks**:
- API calls: 300-1500ms each
- LLM calls: 1-5 seconds each (6 nodes × iterations)
- Network latency

### Token Usage

Approximate tokens per run:
- Query analysis: 500-1000 tokens
- Planning: 800-1500 tokens
- Tool query gen (3 tools): 1500-2500 tokens
- Synthesis: 2000-5000 tokens (depends on result size)
- Verification: 1000-2000 tokens
- Report generation: 3000-8000 tokens

**Total for 1 iteration**: ~10,000-20,000 tokens
**Total for 3 iterations**: ~30,000-60,000 tokens

Using Gemini 1.5 Flash (FREE tier):
- 15 requests/minute limit
- 1,500 requests/day limit
- 1M token context window
- Within limits for all test queries

## Key Differences from Phase 1

| Aspect | Phase 1 | Phase 2 |
|--------|---------|---------|
| Nodes | 1 placeholder | 6 reasoning nodes |
| LLM usage | None | All nodes use LLM |
| Tool calls | None | Real API calls |
| Decision making | Hardcoded flow | Autonomous decisions |
| Loop | Linear only | Self-reflection loop |
| Output | State object | Markdown reports |
| Autonomy | Zero | Full autonomy |

## Success Criteria

Phase 2 is complete when:

✅ All 6 nodes implemented with LLM reasoning
✅ All nodes return expected output formats (JSON/markdown)
✅ Tools are called with LLM-generated queries
✅ Synthesis cross-references findings from multiple tools
✅ Verification node makes autonomous continue/stop decisions
✅ Self-reflection loop works (can iterate 2+ times)
✅ Reports are well-structured with citations
✅ All 7 tests pass
✅ End-to-end test produces valid report from real query
✅ No crashes or critical errors

## Common Issues & Debugging

### Issue: LLM returns invalid JSON

**Symptom**: `_parse_llm_json()` raises ValueError

**Causes**:
- LLM wrapped JSON in markdown code blocks
- LLM added explanatory text before/after JSON
- Actual JSON syntax error

**Solution**: The `_parse_llm_json()` helper handles markdown blocks. If still failing, check:
1. Prompt is clear about "return ONLY JSON"
2. Temperature not too high (> 0.5 can cause format drift)
3. LLM response in logs

### Issue: Verification always continues/stops

**Symptom**: Agent always takes same path regardless of query

**Causes**:
- Verification prompt too lenient/strict
- Confidence thresholds misconfigured
- LLM not actually evaluating quality

**Solution**:
1. Check verification scores in reasoning trace
2. Adjust thresholds in prompt if needed
3. Review prompt clarity

### Issue: Tool execution fails

**Symptom**: No results in tool_results

**Causes**:
- API rate limiting
- Network error
- Invalid query parameters

**Solution**:
1. Check `tool_call_history` for error messages
2. Run Day 1 tests to verify API connectivity
3. Check logs/medagent.log

### Issue: Report has hallucinated information

**Symptom**: Report contains facts not in tool results

**Causes**:
- LLM adding external knowledge
- Synthesis prompt not strict enough

**Solution**:
1. Review REPORT_GENERATION_PROMPT - should emphasize grounding
2. Check if synthesis properly extracted facts
3. Lower temperature for report generation (currently 0.4)

## Next Steps

Phase 2 is complete! The agent is now fully autonomous. Next steps:

1. **Experiment**: Try different queries, observe agent decisions
2. **Tune**: Adjust prompts, temperatures, thresholds based on results
3. **Extend**: Add new tools (DrugBank, UniProt, etc.)
4. **Optimize**: Cache LLM calls, parallelize API requests
5. **Evaluate**: Create benchmark queries, measure quality metrics

## Conclusion

Phase 2 transforms MedAgent from infrastructure into a **real autonomous agent**. The key innovations:

1. **Autonomous Planning**: Agent decides its own research strategy
2. **Dynamic Execution**: LLM generates optimal queries for each tool
3. **Self-Reflection**: Agent evaluates its own work and iterates
4. **Cross-Referencing**: Synthesizes findings from multiple sources
5. **Professional Output**: Generates publication-quality reports

This is not a chatbot wrapper - it's a **self-directed research assistant** that autonomously investigates complex drug discovery questions.

---

**Phase 2 Complete!** 🎉 The agent is ready for real-world drug discovery research.
