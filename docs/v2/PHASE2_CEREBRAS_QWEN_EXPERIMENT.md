# Phase 2 — Cerebras Qwen 3.8 27B Experiment (2026-09-24)

## Scope and independence from the GPT-OSS round

This is a fresh, independent Phase-2 candidate evaluation of Cerebras
`qwen-3.8-27b`, separately authorized and NOT a continuation of the
GPT-OSS-120B experiment, which is **permanently, finally rejected** (3
rounds, `docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md`) with no further calls made
against it in this round. **Zero semantic tuning** was permitted for Qwen:
no prompt revisions of any kind, including the one revision GPT-OSS
received (`CEREBRAS_INTENT_CLARIFIED_PROMPT`/`A_PRIMARY_INTENT_RULE`), since
that revision was created and evaluated only within the rejected GPT-OSS
experiment and was **never accepted into the active control**
(`STRUCTURED_EXTRACTION_PROMPT` itself, what `candidate_b_structured`/
Nemotron actually calls, was never touched by it — confirmed by reading
`nlu/extractor.py` lines ~1206-1246 and `nlu_final_model_selection.json`).

**Prompt decision**: Qwen uses `STRUCTURED_EXTRACTION_PROMPT` (the active
control prompt, unmodified) with the identical `.format(query=query,
b_vs_g_rule=B_VS_G_RULE, d_vs_e_rule=DI_VS_E_RULE)` call signature as
`candidate_b_structured`. Taxonomy, schema, normalization: all unchanged.

## Code change (mechanical, not semantic)

`nlu/extractor.py::_extract_via_cerebras` previously hardcoded
`CEREBRAS_INTENT_CLARIFIED_PROMPT` (the GPT-OSS-only revision) as its prompt
source for BOTH candidate_f and candidate_g — a latent bug that would have
silently given Qwen the GPT-OSS-only revision had it not been caught before
any pilot call. Fixed by adding optional `prompt_template` and
`reasoning_effort` parameters (default preserves candidate_f's exact prior
behavior); `extract_candidate_g_cerebras_qwen` now explicitly passes
`prompt_template=STRUCTURED_EXTRACTION_PROMPT`, `reasoning_effort='none'`.
Full test suite: 139 passed, 0 failed, both before and after.

## Provider verification

`artifacts/v2/nlu_cerebras_qwen_provider_verification.json`. Key facts,
live-fetched from `inference-docs.cerebras.ai` (2026-09-24): model ID
`qwen-3.8-27b`, active; context 64K free-trial/128K paid; max completion
32K free-trial/40K paid; strict JSON Schema structured outputs supported;
`reasoning_effort` supports `none` (confirmed both by the model-specific
doc page and empirically via the smoke test); pricing $0.99/$1.49 per
million input/output tokens; Free Trial rate limits 5 RPM / 30K TPM
uncached / 90K TPM total / 1M TPD (same envelope as gpt-oss-120b's
previously-verified limits, independently re-confirmed rather than
assumed).

## Budget

`artifacts/v2/nlu_cerebras_qwen_budget_plan.json`. Prior cumulative
Cerebras spend (verified from artifact `usage_and_cost` fields, not prose):
$0.03506745 of the $0.50 cap. Remaining before Qwen: $0.46493255.
Projected total (smoke + pilot + full dev + retry margin): ~$0.186-0.216,
comfortably within budget — no cap increase needed.

## Reasoning-control smoke test (1 of max 2 calls)

`reasoning_effort='none'` on the first attempt: HTTP 200, schema_valid=True,
1 llm_call (0 retries), 610.8ms wall, 2082 input / 294 output tokens,
**reasoning_tokens=0** (confirmed no meaningful reasoning trace or token
burn). Frozen without a second smoke call. Query used was synthetic,
verified absent from all benchmark/pilot/test artifacts.
`artifacts/v2/nlu_cerebras_qwen_frozen_config.json`.

## 8-case pilot

`artifacts/v2/nlu_cerebras_qwen_pilot_plan.json` /
`nlu_cerebras_qwen_pilot_results.json`. 8 fresh dev-split query_ids,
programmatically verified zero overlap (query_id, exact text,
`template_group`) with the GPT-OSS round-2 pilot, GPT-OSS round-3 pilot, and
the 105-example consumed test split; Phase-10 data does not yet exist.
Covered: true `A_literature_evidence`, `G_constraint_heavy` (x2, distinct
instances), `E_multi_hop_research` (a class GPT-OSS collapsed to A on),
`D_cross_source_synthesis`, an `I_ambiguous` proxy (no true
ambiguous-abbreviation gold example exists in the dev split, same disclosed
limitation as prior rounds), `C_compound_target` (HER2/ERBB2,
gene/protein/target-ambiguous), `B_clinical_trial_landscape`.

**Result: 8/8 intent correct, 8/8 schema-valid, 0 retries, 13/13 gold
entity mentions correctly typed and normalized, 0 fabricated IDs, all 7
gold constraint-field instances captured correctly, the ambiguous case
correctly flagged `is_ambiguous=true` with a sound reason, no B/G
confusion.** True latency (throttle-separated, via an instrumented wrapper
around `wait_for_rate_limit`, correcting the exact measurement mistake
identified in GPT-OSS round 2): P50 481.7ms, max 918.9ms, vs control
19150ms/66983ms — decisive. **PILOT: PASS.**

## Full dev evaluation (45 examples)

`artifacts/v2/nlu_cerebras_qwen_candidate_results.json`. Same dev split,
same frozen config, zero further tuning. Entity F1 micro 0.9718 (control
0.9008, +0.071), intent accuracy 0.9111 / macro-F1 0.8884 (control 0.848,
+0.040), constraint F1 micro 0.84375 (control 0.788-0.818, +0.026 to
+0.056), fabricated IDs 0, schema-parse success 1.0 (control 0.911),
normalization accuracy@1 1.0. Latency (throttle-corrected): P50 471.0ms,
P90 996.5ms, P95 1175.9ms, max 3159.2ms — a 97.5%/98.2% P50/P95 reduction,
decisively past both the >=60% bar and the preferred P50<=5s/P95<=15s bar.

4/45 intent errors: 1x `G_constraint_heavy`→`B_clinical_trial_landscape`
(12.5% of G support), 1x `C_compound_target`→`A_literature_evidence`
(isolated), 2x `E_multi_hop_research`→`D_cross_source_synthesis` (50% of E
support — a pre-existing D/E boundary confusion also observed historically
on the GPT-OSS candidate, structurally distinct from a generic-fallback
collapse). No class shows >=80% one-directional misclassification; no
false-A collapse pattern. Constraint field breakdown: no field F1<0.3 at
support>=5 (the disqualifying threshold used throughout this project).

Cost: 93,628 input / 11,654 output tokens across 45 calls, ~$0.1101.
Combined with the smoke test (~$0.0025) and pilot (~$0.0196), this round's
total spend: **~$0.1321**. Cumulative across all Cerebras rounds (GPT-OSS +
Qwen): **~$0.1672 of the $0.50 cap (~33.4%)**.

## Decision: ADOPT

All 19 Step-31 acceptance conditions hold (see
`artifacts/v2/nlu_frozen_config.json`'s `final_acceptance_step31_check`).
`candidate_g_cerebras_qwen` is now the frozen Phase-2 NLU architecture
(`config_version: 3`). This resolves Phase 2's sole remaining open exit
gate (latency); the full 23-gate re-audit
(`docs/v2/PHASE2_FINAL_GATE_AUDIT.md`) now shows 23/23 PASS. Prior
architecture (Nemotron, `config_version: 2`) archived verbatim at
`artifacts/v2/nlu_frozen_config_v2_pre_qwen_archive.json`. **Phase 3 is
still NOT self-authorized by this outcome** — a human must review and
explicitly authorize.

## Deployment cost projection (Phase-2 NLU stage only)

Measured cost/call: ~$0.002446 (mean 2080.6 input + 259.0 output tokens at
$0.99/$1.49 per million). Projected: 100 calls ≈ $0.245; 1,000 calls ≈
$2.446; 10,000 calls ≈ $24.46. This is the Phase-2 NLU-extraction stage
only, not a projection of full MedAgent system cost.
