"""Static tool registry and the pre-execution validation boundary.

Per docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md Section 5:

    ToolCall model validation -> registry lookup -> argument-schema
    validation -> execution

This module owns the middle two steps (registry lookup, argument-schema
validation) via `ToolRegistry.validate_call`. It deliberately does NOT
execute anything - `ToolRegistry.get_execution_fn` hands back a callable for
a LATER, separate execution step to invoke; `validate_call` itself never
calls it.

Everything is statically registered at module import time, directly
referencing the real tool classes (PubMedTool, ClinicalTrialsTool,
ChEMBLTool). There is no `eval`/`exec`/dynamic import from a string and no
arbitrary-callable execution anywhere in this module - this is what makes
"an unknown/hallucinated tool name reaches execution" structurally
impossible, closing the exact gap the audit found (today's only guard is an
ad hoc `if tool_name not in tool_instances` dict-membership check done at
execution time in agent/nodes.py, not at selection time).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, Type, Union

from pydantic import BaseModel, ValidationError

from orchestration.models import (
    ChEMBLGetDrugInfoArgs,
    ChEMBLResolveCompoundNameArgs,
    ChEMBLSearchByIndicationArgs,
    ChEMBLSearchByTargetArgs,
    ClinicalTrialsSearchArgs,
    PubMedSearchArgs,
    ToolCall,
    ToolErrorCategory,
    ToolName,
)
from tools.chembl_tool import ChEMBLTool
from tools.clinical_trials_tool import ClinicalTrialsTool
from tools.pubmed_tool import PubMedTool


class RegistryError(Exception):
    """Typed error for registry/validation failures - never a bare crash.
    Carries a `category` (ToolErrorCategory) so callers can attribute the
    failure without string-matching an exception message."""

    def __init__(self, message: str, category: ToolErrorCategory):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ToolBinding:
    """One statically-registered (tool_name, operation) -> execution
    binding."""

    tool_name: ToolName
    operation: str
    argument_schema: Type[BaseModel]
    # Bound to a real tool client method, e.g. PubMedTool().search_pubmed.
    # Takes only the validated argument model's fields as kwargs.
    execute_fn: Callable[..., Any]
    timeout_policy: str = "default"
    retry_policy: str = "default"
    source_metadata: Dict[str, Any] = field(default_factory=dict)


def _call_with_args(fn: Callable[..., Any], args: BaseModel) -> Any:
    """Invoke a bound tool method with a validated Pydantic argument
    model's fields as keyword arguments. Never receives raw/untyped input -
    `args` has already passed schema validation by the time this runs."""

    return fn(**args.model_dump())


class ToolRegistry:
    """Centralized, statically-built (tool_name, operation) -> binding map.

    Constructed once at module load time (see `DEFAULT_REGISTRY` below) by
    directly instantiating the three real tool clients and referencing
    their real bound methods - no string-keyed dynamic dispatch."""

    def __init__(self) -> None:
        self._bindings: Dict[Tuple[ToolName, str], ToolBinding] = {}

    def register(self, binding: ToolBinding) -> None:
        key = (binding.tool_name, binding.operation)
        if key in self._bindings:
            raise ValueError(f"Duplicate registry binding for {key}")
        self._bindings[key] = binding

    def lookup(self, tool_name: ToolName, operation: str) -> Optional[ToolBinding]:
        """Returns the binding, or None if (tool_name, operation) is not
        registered. Never raises for an unknown pair - callers that need a
        hard error use `require`."""

        return self._bindings.get((tool_name, operation))

    def require(self, tool_name: ToolName, operation: str) -> ToolBinding:
        """Like `lookup`, but raises a typed RegistryError instead of
        returning None - used by `validate_call`, which must fail loudly
        (not silently skip) when a plan references an unregistered
        (tool_name, operation) pair."""

        binding = self.lookup(tool_name, operation)
        if binding is None:
            raise RegistryError(
                f"No registered binding for tool_name={tool_name!r} operation={operation!r}",
                category=ToolErrorCategory.UNREGISTERED_TOOL,
            )
        return binding

    def validate_call(self, tool_call: ToolCall) -> ToolCall:
        """Boundary function: registry lookup, THEN argument schema
        validation, in that order - mirroring the contract's pipeline.

        This function performs VALIDATION ONLY. It never invokes
        `execute_fn` and never issues an HTTP request. On success it
        returns the same (already-validated, since ToolCall's own pydantic
        construction already ran) tool_call unchanged, so callers can chain
        `validate_call(call)` before their own separate execution step.

        Raises:
            RegistryError: if (tool_call.tool_name, tool_call.operation) is
                not registered (category=UNREGISTERED_TOOL), or if the
                operation is registered for a different tool_name than the
                one requested (category=UNSUPPORTED_OPERATION), or if the
                arguments fail the registered schema's own validation
                (category=VALIDATION_ERROR - defensive; in practice
                `tool_call.arguments` is already an instance of the correct
                typed model by construction, since ToolCall is a
                discriminated union keyed on `operation`).
        """

        binding = self.require(tool_call.tool_name, tool_call.operation)

        if not isinstance(tool_call.arguments, binding.argument_schema):
            # Defensive re-validation: re-run the registered schema against
            # the arguments' own field values. Structurally this branch
            # should be unreachable given ToolCall's discriminated union
            # (operation uniquely determines the arguments type), but this
            # keeps validate_call() correct even if a future ToolCall
            # variant loosens that guarantee.
            try:
                binding.argument_schema.model_validate(
                    tool_call.arguments.model_dump()
                    if isinstance(tool_call.arguments, BaseModel)
                    else tool_call.arguments
                )
            except ValidationError as exc:
                raise RegistryError(
                    f"Arguments for {tool_call.tool_name}/{tool_call.operation} failed schema validation: {exc}",
                    category=ToolErrorCategory.VALIDATION_ERROR,
                ) from exc

        return tool_call

    def get_execution_fn(self, tool_name: ToolName, operation: str) -> Callable[[BaseModel], Any]:
        """Returns a zero-argument-away callable `f(validated_args) -> Any`
        for a registered (tool_name, operation) pair, for a SEPARATE
        execution step to call. Raises RegistryError (not a crash) if
        unregistered. This module never calls the returned callable itself."""

        binding = self.require(tool_name, operation)

        def _bound(args: BaseModel) -> Any:
            return _call_with_args(binding.execute_fn, args)

        return _bound

    def registered_pairs(self) -> Tuple[Tuple[ToolName, str], ...]:
        return tuple(self._bindings.keys())


def _build_default_registry() -> ToolRegistry:
    """Statically builds the registry from the real tool clients. Runs once
    at module import time. Constructing the tool client instances here
    (PubMedTool(), ClinicalTrialsTool(), ChEMBLTool()) is safe - their
    __init__ only sets up config/rate-limit/session state (tools/base_tool.py),
    it does not issue any network call."""

    registry = ToolRegistry()

    pubmed = PubMedTool()
    clinical_trials = ClinicalTrialsTool()
    chembl = ChEMBLTool()

    registry.register(
        ToolBinding(
            tool_name=ToolName.PUBMED,
            operation="search_pubmed",
            argument_schema=PubMedSearchArgs,
            execute_fn=pubmed.search_pubmed,
            timeout_policy="pubmed_default",
            retry_policy="pubmed_default",
            source_metadata={"client": "tools.pubmed_tool.PubMedTool"},
        )
    )

    registry.register(
        ToolBinding(
            tool_name=ToolName.CLINICAL_TRIALS,
            operation="search_trials",
            argument_schema=ClinicalTrialsSearchArgs,
            execute_fn=clinical_trials.search_trials,
            timeout_policy="clinical_trials_default",
            retry_policy="clinical_trials_default",
            source_metadata={"client": "tools.clinical_trials_tool.ClinicalTrialsTool"},
        )
    )

    registry.register(
        ToolBinding(
            tool_name=ToolName.CHEMBL,
            operation="search_by_target",
            argument_schema=ChEMBLSearchByTargetArgs,
            execute_fn=chembl.search_by_target,
            timeout_policy="chembl_default",
            retry_policy="chembl_default",
            source_metadata={"client": "tools.chembl_tool.ChEMBLTool"},
        )
    )

    registry.register(
        ToolBinding(
            tool_name=ToolName.CHEMBL,
            operation="search_by_indication",
            argument_schema=ChEMBLSearchByIndicationArgs,
            execute_fn=chembl.search_by_indication,
            timeout_policy="chembl_default",
            retry_policy="chembl_default",
            source_metadata={"client": "tools.chembl_tool.ChEMBLTool"},
        )
    )

    registry.register(
        ToolBinding(
            tool_name=ToolName.CHEMBL,
            operation="get_drug_info",
            argument_schema=ChEMBLGetDrugInfoArgs,
            execute_fn=chembl.get_drug_info,
            timeout_policy="chembl_default",
            retry_policy="chembl_default",
            source_metadata={"client": "tools.chembl_tool.ChEMBLTool"},
        )
    )

    registry.register(
        ToolBinding(
            tool_name=ToolName.CHEMBL,
            operation="resolve_compound_name",
            argument_schema=ChEMBLResolveCompoundNameArgs,
            execute_fn=chembl.resolve_compound_name,
            timeout_policy="chembl_default",
            retry_policy="chembl_default",
            source_metadata={"client": "tools.chembl_tool.ChEMBLTool"},
        )
    )

    return registry


# Module-level singleton, built once from the real tool clients - the
# single source of truth for "what (tool_name, operation) pairs exist."
DEFAULT_REGISTRY: ToolRegistry = _build_default_registry()
