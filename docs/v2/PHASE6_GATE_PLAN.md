# Phase 6 Gate Plan

Predeclared, before candidate measurement, per `docs/v2/PHASE6_GROUNDED_GENERATION_CONTRACT.md`.

## 1. Predeclared metrics

**Structural grounding:** factual units with >=1 Evidence ID (%); invalid
Evidence-ID reference rate; unknown Evidence-ID count; citation-to-nonexistent-
Evidence count; uncited factual-unit count.

**Content coverage:** required-gold-fact coverage (%); forbidden/unsupported
gold-fact occurrence count.

**Citation structure:** deterministic citation-compilation success (%);
inline citation adjacency success (%); duplicate citation/reference
handling correctness; reference-entry-without-Evidence count; Evidence-
cited-but-missing-reference-entry count.

**Abstention:** zero-Evidence abstention correctness (%); insufficient-
Evidence abstention correctness (%).

**Conflict handling:** conflict-preservation correctness on conflict cases (%).

**Output quality:** schema-valid generation rate (%); generation completion
rate (%); natural-language rendering success (%).

**Reliability:** provider errors; retries; malformed structured output
count; deterministic validation failure count.

**Performance:** model calls/query; input/output tokens/query; latency
mean/P50/P90/P95/max; cost/query; total benchmark cost. Generation latency
reported separately from retrieval/Evidence-normalization/network-source
latency (never blended).

No composite score. None of these metrics may be called "citation
faithfulness" or "semantic grounding accuracy" — those require Phase 7's
independent judge methodology and are explicitly out of scope here.

## 2. Hard safety gates — frozen, all must equal 0 (except where noted)

| Gate | Required value |
|---|---|
| Unknown Evidence IDs referenced | 0 |
| Reference entry without real Evidence | 0 |
| Fabricated source IDs | 0 |
| Fabricated source URLs | 0 |
| Secret/auth leaks | 0 |
| Factual unit with no support binding (excl. explicitly allowed non-factual/abstention types) | 0 |
| Zero-Evidence case producing a supported factual claim | 0 |
| Model-generated final citation number used as source of truth | 0 |
| Unserializable final answer object | 0 |
| Uncaught invalid structured output | 0 |

Not weakened after seeing results, same discipline as Phases 2-5.
