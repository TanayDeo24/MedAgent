# ENGINEERING_GAPS.md

Gap analysis grouped per the audit spec. All citations to git-history commit
`14a59b9` unless marked WORKING TREE.

## Correctness
- No automated check that inline citations in the LLM-written prose actually
  correspond to the specific claim next to them — only the citation *list*
  and the deterministic compound *table* are verified-by-construction
  (`agent/nodes.py:225-315`); narrative prose citations are LLM-placed and
  unchecked.
- `hallucination_judge.py`'s own documented failure rate (~39% success, i.e.
  ~61% of judge calls fail outright, `RESULTS.md` §3) means most runs ship
  with **no working hallucination measurement at all**, not a low one.

## Core functional
- Task success rate is measured at 18-38% (`RESULTS.md` §4), driven mainly
  by the agent's own confidence self-assessment landing below the 0.5
  threshold, not crashes — i.e. the core research loop runs to completion but
  frequently doesn't consider itself successful. This is a functional gap in
  the underlying agent quality, not an infrastructure bug.
- Self-correction rate is 91-93% (nearly every run loops), but this does not
  correlate with higher success (`RESULTS.md` §4 explicitly flags this as
  "looping isn't reliably converging on success").

## Search / retrieval
- Recall@10 tops out at 0.66 (grounding set, hybrid) against a self-measured
  oracle ceiling of 0.95 for that same set (`PHASE3_RETRIEVAL_QUALITY_COMPLETE.md`
  §11.5) — a real, unclosed ~0.29 gap the project's own optimization pass
  (HyDE, alternate embeddings, weighted RRF) failed to close (§12 of that
  doc: none of those techniques beat the shipped baseline).
- No nDCG, MRR, or any rank-quality metric beyond Recall@k is implemented
  anywhere (`grep` confirmed zero occurrences).

## Heterogeneous-source
- Cross-source linking is limited to one mechanism: case-insensitive
  substring match of a compound name against a trial's intervention list
  (`agent/nodes.py:270-283`) — no ID-based linkage (e.g. ChEMBL ID ↔ trial
  intervention ID) exists because the underlying APIs don't expose one; this
  is a real data-integration ceiling, not an implementation gap that can be
  trivially fixed.

## NLU / query understanding
- All query understanding (target/disease/compound extraction, query-type
  classification) is done by prompting the general-purpose LLM with no
  extraction-accuracy evaluation of its own — `query_analysis_node`'s output
  is never separately validated against ground truth anywhere in
  `evaluation/`.

## Grounding / citation
- `REPORT_GENERATION_PROMPT` (prompts.py:423-441) *instructs* the LLM not to
  invent its own compound table, and the code enforces this by post-hoc
  string replacement — but no equivalent enforcement exists for any other
  section of the report (Key Findings, Detailed Analysis, Clinical Evidence)
  — those remain free-text, LLM-authored, and only prompt-instructed to stay
  grounded.

## Agent/tool-reliability
- 9 distinct hallucinated (nonexistent) tool names were attempted a combined
  12+ times across 60 cases even after prompt-tightening (`RESULTS.md`
  "Tool-hallucination counting" §3) — a real, only partially mitigated
  reliability gap in tool selection.
- No native LLM function/tool-calling API is used (`ACTUAL_ARCHITECTURE.md`
  §4) — the JSON-emit/Python-dispatch pattern is inherently more fragile to
  exactly this kind of hallucination than schema-constrained tool calling
  would be.

## Evaluation
- Sample sizes throughout are small by ML-evaluation standards: 60 test
  cases (Phase 2), 30×2 arms (Phase 3) — enough to move directional
  findings but explicitly insufficient, by the project's own repeated
  admission, for precise percentage claims on the hallucination-judge metric.
- The Phase 2 run's easy-difficulty tier has **zero** measured
  `task_completed` data (all 18 easy cases fall in the reconstructed-from-logs
  set, `RESULTS.md` §2) — a real, acknowledged coverage gap.

## Testing
- **Currently zero tests are collectible in the working tree** (`INITIAL_STATE.md`
  §1) — this is the single largest testing gap in the repository's present
  state, independent of what test pass rates were historically reported.
- Historical claim (`RESULTS.md` §6): "pytest tests/: 40/42 pass — same 2
  pre-existing rate-limit-test failures documented since PHASE1_COMPLETE.md."
  This audit could not independently reproduce this number (no runnable
  source in the working tree, and re-running against the git-history snapshot
  was out of scope for a read-only audit that must not alter the working
  tree) — classified **UNVERIFIED BY THIS AUDIT**, not confirmed.

## Performance
- Average per-case latency 177-210s (`RESULTS.md` §4) — not viable for
  interactive/real-time use as-is; acceptable only for an offline/batch
  research-assistant use case.
- No token-budget-aware context truncation strategy beyond a hard `[:10]`
  results slice per tool in `synthesis_node` (`nodes.py:774-778`) and raising
  `max_tokens` on specific nodes — no adaptive/dynamic context management.

## Observability
- `logs/medagent.log` (WORKING TREE, 19,159 lines) is dominated by synthetic
  unit-test log lines (`"Tool call succeeded: test"`, `"nonexistent query
  xyz123"`) rather than traces of real production agent runs — the log file
  present in this repository right now is not strong evidence of sustained
  real-world usage, only of unit-test exercising of `tools/base_tool.py`'s
  logging path.
- Per-dispatch LLM timing logs (`[LLM DISPATCH]`/`[LLM DISPATCH RESULT]`,
  `llm_config.py:229-231,238-241,265`) are real and detailed, added
  specifically to diagnose the 429/hang incident — genuine, useful
  observability, but narrowly scoped to the LLM call layer, not end-to-end
  tracing.

## Reproducibility
- No CI configuration file was found anywhere in the repository (working
  tree or git history) — evaluation runs are manual, local, single-machine
  (explicit Apple Silicon/Metal-specific bug found and fixed,
  `RESULTS_RAG_COMPARISON.md` §2), with no automated re-run on a schedule or
  on commit.
- **This audit's own reproducibility is limited**: the working tree has no
  runnable source (§1), and no live-API run was attempted (see
  `AUDIT_REPORT.md` §35) — every metric in this audit is traced to a
  machine-generated artifact already on disk, not independently regenerated.

## Deployment / serving
- No web server, API, GraphQL layer, containerization (`Dockerfile`), or CI
  config exists anywhere in git history at `14a59b9` — `main.py` is a local
  synchronous CLI only. Any "deployment"-shaped claim is entirely unbuilt.

## Documentation
- The root `*_COMPLETE.md` narrative docs are, on close reading, unusually
  honest and self-critical (they explicitly flag their own predecessors'
  fabricated numbers) — but `AUDIT_CURRENT_STATE.md` itself is now stale
  (describes a pre-fix, pre-RAG state) and remains in the repo without a
  correction note, which could mislead a reader who trusts the most recent
  file mtime over actual git history.
- No single up-to-date architecture document reflects the final `14a59b9`
  state; `docs/architecture.md`/`docs/phase1_architecture.md`/
  `docs/phase2_architecture.md` are dated snapshots, not a living doc.

## JD-evidence gaps
- No demonstrated deployment/serving capability (API, container, CI/CD).
- No demonstrated multi-turn conversation / session memory (each `main.py`
  invocation is a single independent query, `create_initial_state` starts
  fresh every time — `agent/state.py:212-267`).
- No demonstrated fine-tuning, model training, or offline learning from
  evaluation feedback (verification/self-reflection affects only the current
  run's loop, not any persisted model or prompt update).
