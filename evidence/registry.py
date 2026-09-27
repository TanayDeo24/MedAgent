"""Static adapter registry - the (source_type, sub_key) -> adapter function
dispatch table for evidence/adapters.py.

Follows orchestration/registry.py's `ToolRegistry` pattern structurally:
everything is registered at module import time, directly referencing the
real adapter functions in `evidence.adapters` - no `eval`/dynamic import/
lookup-by-arbitrary-string, and an unregistered key raises a typed error
deterministically instead of failing silently or falling through to a
generic handler.

`sub_key` exists because, unlike orchestration's single-callable-per-
(tool, operation) bindings, more than one *granularity* of Evidence can come
from the same `SourceType`:
    - PubMed has two structurally different adapters (RAG chunk-level vs.
      live-API article-level) that take different input shapes, per the
      audit's finding that these two paths are irreconcilably different
      (`Document` dataclass vs. a plain parsed dict).
    - ChEMBL has two structurally different adapters (the molecule/
      indication-shaped `chembl_target_or_indication_result_to_evidence`,
      parameterized further by the specific ChEMBL operation name, vs.
      `chembl_resolve_compound_name_to_evidence`'s distinct hand-built shape).
`sub_key` is a plain string naming which adapter/granularity to use - NOT an
arbitrary caller-supplied dispatch key executed dynamically; the only valid
values are the ones registered below, enforced by `require`/`normalize`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from evidence.adapters import (
    chembl_resolve_compound_name_to_evidence,
    chembl_target_or_indication_result_to_evidence,
    clinical_trial_to_evidence_records,
    pubmed_live_result_to_evidence,
    pubmed_rag_document_to_evidence,
)
from evidence.models import Evidence, SourceType


class EvidenceAdapterError(Exception):
    """Typed error for an unregistered (source_type, sub_key) pair - never a
    bare KeyError/AttributeError reaching the caller."""


@dataclass(frozen=True)
class AdapterBinding:
    """One statically-registered (source_type, sub_key) -> adapter function
    binding. `returns_list` records whether the underlying adapter already
    returns `List[Evidence]` (ClinicalTrials) vs. a single `Evidence` or
    `Optional[Evidence]` (every other adapter) - `normalize()` uses this to
    always hand the caller back a uniform `List[Evidence]`, never a bare
    `Evidence`/`None`."""

    source_type: SourceType
    sub_key: str
    adapter_fn: Callable[..., Any]
    returns_list: bool


class EvidenceAdapterRegistry:
    """Centralized, statically-built (SourceType, sub_key) -> AdapterBinding
    map, built once at import time by directly referencing the real adapter
    functions in `evidence.adapters`."""

    def __init__(self) -> None:
        self._bindings: Dict[Tuple[SourceType, str], AdapterBinding] = {}

    def register(self, binding: AdapterBinding) -> None:
        key = (binding.source_type, binding.sub_key)
        if key in self._bindings:
            raise ValueError(f"Duplicate adapter registry binding for {key}")
        self._bindings[key] = binding

    def lookup(self, source_type: SourceType, sub_key: str) -> Optional[AdapterBinding]:
        """Returns the binding, or None if (source_type, sub_key) is not
        registered. Never raises - callers needing a hard error use
        `require`."""

        return self._bindings.get((source_type, sub_key))

    def require(self, source_type: SourceType, sub_key: str) -> AdapterBinding:
        """Like `lookup`, but raises `EvidenceAdapterError` instead of
        returning None - deterministic failure on an unknown key rather than
        a silent no-op or an arbitrary-string dynamic lookup."""

        binding = self.lookup(source_type, sub_key)
        if binding is None:
            raise EvidenceAdapterError(
                f"No registered evidence adapter for source_type={source_type!r} "
                f"sub_key={sub_key!r}. Registered keys: "
                f"{sorted((s.value, k) for s, k in self._bindings)}"
            )
        return binding

    def registered_keys(self) -> Tuple[Tuple[SourceType, str], ...]:
        return tuple(self._bindings.keys())

    def normalize(
        self,
        source_type: SourceType,
        sub_key: str,
        raw_result: Any,
        **kwargs: Any,
    ) -> List[Evidence]:
        """Dispatch to the correct adapter and always return a `List[Evidence]`
        (even for single-record adapters, and even when the adapter declines
        to produce a record at all - e.g. a placeholder PubMed abstract or a
        `no_match`/`ambiguous_match` ChEMBL resolution both correctly yield
        `[]` here, not an error), for a uniform caller interface.

        Raises `EvidenceAdapterError` for an unregistered (source_type,
        sub_key) pair. Any exception the adapter itself raises (e.g. a
        missing/empty source id) propagates unchanged - this method never
        swallows an adapter's own validation failure.
        """

        binding = self.require(source_type, sub_key)
        result = binding.adapter_fn(raw_result, **kwargs)

        if binding.returns_list:
            return list(result)
        if result is None:
            return []
        return [result]


def _build_default_registry() -> EvidenceAdapterRegistry:
    registry = EvidenceAdapterRegistry()

    registry.register(
        AdapterBinding(
            source_type=SourceType.PUBMED,
            sub_key="rag",
            adapter_fn=pubmed_rag_document_to_evidence,
            returns_list=False,
        )
    )
    registry.register(
        AdapterBinding(
            source_type=SourceType.PUBMED,
            sub_key="live",
            adapter_fn=pubmed_live_result_to_evidence,
            returns_list=False,
        )
    )
    registry.register(
        AdapterBinding(
            source_type=SourceType.CLINICAL_TRIALS,
            sub_key="trial",
            adapter_fn=clinical_trial_to_evidence_records,
            returns_list=True,
        )
    )
    for operation in ("search_by_target", "search_by_indication", "get_drug_info"):
        registry.register(
            AdapterBinding(
                source_type=SourceType.CHEMBL,
                sub_key=operation,
                adapter_fn=(
                    lambda raw_result, _op=operation, **kwargs: (
                        chembl_target_or_indication_result_to_evidence(
                            raw_result, chembl_operation=_op, **kwargs
                        )
                    )
                ),
                returns_list=False,
            )
        )
    registry.register(
        AdapterBinding(
            source_type=SourceType.CHEMBL,
            sub_key="resolve_compound_name",
            adapter_fn=chembl_resolve_compound_name_to_evidence,
            returns_list=False,
        )
    )

    return registry


# Module-level singleton - single source of truth for "which
# (source_type, sub_key) adapters exist," mirroring
# orchestration/registry.py's DEFAULT_REGISTRY.
DEFAULT_ADAPTER_REGISTRY: EvidenceAdapterRegistry = _build_default_registry()
