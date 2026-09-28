# Phase 8 — Gate Plan (predeclared before any dev run)

Per this project's established discipline (Phases 6/7): metrics and
benchmark design are predeclared here BEFORE any Phase-8 evaluation is run,
never adjusted after seeing results.

## Predeclared metrics (`EVALUATION_CONTRACT.md` §11)

| Metric | How measured this phase |
|---|---|
| Gap identification accuracy | Human-reviewed (this session): for each dev case, does the detected gap set match the case's designed intent (A-J categories, Section 4 below)? |
| Follow-up source correctness | Does the executed action's tool selection match its gap's `target_source_category`? |
| Additional relevant evidence gained | `new_evidence_ids` count from `evidence_merge_node`, per action |
| **Quality improvement after follow-up (primary)** | Claim Support Precision delta, via the frozen Candidate B judge, pre- vs. post-follow-up answer, on the SAME case |
| Unnecessary-loop rate | fraction of executed actions with `status=executed_unproductive` or `executed_duplicate_only` |
| Mean loops/query | mean `research_iteration` at stop, across dev cases |
| Loop termination correctness | does the case's actual `research_stop_reason` match its designed-correct stop reason? |

## Benchmark design (Section 4 of `PHASE8_INITIAL_AUDIT.md`'s Step-4 categories)

A dedicated Phase-8 dev benchmark (NOT Phase 7's grounding benchmark, NOT
any Phase-10 held-out set - none exists) built from real, previously-unused
Phase-5 manifest records (same methodology as the Phase-7 fresh supplement:
`evidence/adapters.py`, never fabricated). Categories A-J from the
governing directive, mapped to concrete case designs:

| Category | Case design |
|---|---|
| A. initial evidence already sufficient | Full, correct Evidence set given upfront; correct behavior: `SUFFICIENT_EVIDENCE`, 0 follow-up actions |
| B. incomplete but recoverable via 1 follow-up | Evidence deliberately missing one source category; a real, held-back record from that category exists and is injected on the simulated follow-up (see "Live-tool constraint" below) |
| C. multiple source types required | Query whose Phase-2 `requested_evidence_types` spans 2+ categories, only 1 present initially |
| D. first retrieval weak/irrelevant | Evidence present but only weakly supports the claim (triggers `WEAKLY_SUPPORTED_FACT`) |
| E. correct behavior is abstain | No recoverable evidence exists at all; correct stop reason: `SAFE_ABSTENTION` |
| F. follow-up would be redundant | All gaps already attempted; correct stop reason: `NO_PRODUCTIVE_ACTION` |
| G. merge without duplication | The simulated follow-up returns a record already present; `evidence_duplicate_count` must increase, not `new_evidence_ids` |
| H. conflicting evidence | Two records for the same claim disagree; correct gap: `CONFLICTING_EVIDENCE` |
| I. tool/provider fails mid-step | `research_execution_node`'s underlying `tool_orchestration_node` call is made to raise/return a failure (network already blocked in this session - see below); correct behavior: bounded retry accounting, no crash |
| J. would otherwise loop forever without bounds | Every gap type detector, seeded to keep firing; correct stop reason: `BUDGET_EXHAUSTED`, never an infinite loop |

## Live-tool constraint (disclosed, not worked around)

This cloud session's egress proxy denies `eutils.ncbi.nlm.nih.gov`,
`clinicaltrials.gov`, and `www.ebi.ac.uk` (confirmed via direct `curl`,
`connect_rejected`/HTTP 403 - same class of restriction as
`CLOUD_TO_LOCAL_GAP_CLOSURE.md`'s CTL-002/003/004). `research_execution_node`
cannot make a genuine live tool call to acquire new real-world evidence in
this session. Cerebras IS reachable, so `grounded_generation_node` and the
Candidate B judge run genuinely live.

Given this, the dev benchmark's "productive follow-up" cases (B, C, G)
inject the follow-up round's Evidence directly via the same
`evidence/adapters.py` functions used for the initial pass, bypassing only
the live-network tool-execution step of `research_execution_node` (its
gap-detection, action-planning, stop-reason, and evidence-merge/dedup logic
all still run for real, unmocked). This is disclosed explicitly in every
result artifact this produces (`network_simulated_followup: true`) - never
presented as a live end-to-end network demonstration. Cases I (provider
failure) and every pure loop-control/budget case (F, J) require no network
at all and are tested as genuine unit/integration tests
(`tests/test_research_*.py`), with the network-blocked live tool path
itself standing in as the "provider fails" scenario for case I where
applicable.

## What counts as "measured quality delta" for the exit gate

For each Category-B/C/D/H case: Claim Support Precision (Candidate B judge,
live) computed on the PRE-follow-up answer's factual claims, then again on
the POST-follow-up answer's factual claims (same case, same judge config).
Reported as absolute delta + n, per `EVALUATION_CONTRACT.md` §12's
same-benchmark-both-arms rule. If no case shows a measurable improvement,
this is reported honestly as required by the phase's own stop condition -
never rounded up.

## Not run this phase

- Concurrency/load testing (Phase 9).
- Anything touching a Phase-10 held-out set (none exists).
