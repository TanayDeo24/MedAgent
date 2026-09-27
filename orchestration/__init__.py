"""Phase 3 orchestration layer: typed tool models, a static registry, and
deterministic source selection from the frozen Phase 2 `ResearchQuery`.

Scope (see docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md): this package
implements ONLY the typed-model + registry + deterministic-source-selection
layer. It is intentionally NOT wired into agent/nodes.py yet - that
integration is a later step, gated on a candidate-comparison and
architecture-freeze decision this package does not make.

Modules:
    models           - ToolName, ToolErrorCategory, per-tool typed argument
                        schemas, ToolCall, ExecutionPlan, ToolExecutionResult.
    registry         - ToolRegistry: static (tool_name, operation) ->
                        execution binding, with a validate_call() boundary
                        function that performs registry lookup + argument
                        validation WITHOUT executing anything.
    source_selection - select_sources(query: ResearchQuery) -> List[ToolName],
                        a pure deterministic function using
                        ResearchQuery.requested_evidence_types as an input
                        signal (not as an authoritative routing decision).
"""
