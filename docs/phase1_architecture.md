# Phase 1 Architecture - Agent Foundation

## Overview

Phase 1 establishes the foundational infrastructure for MedAgent's autonomous research capabilities. This phase focuses on **plumbing, not intelligence** - we're setting up the state machine and data flow that will power the agent in later phases.

## What Phase 1 Accomplishes

✅ **LLM Integration**: Connect to Google Gemini 1.5 Flash (free tier)
✅ **State Management**: Define complete agent state structure
✅ **Graph Infrastructure**: Build LangGraph skeleton
✅ **Basic Flow**: Single-node placeholder that validates end-to-end execution
✅ **Testing Framework**: Comprehensive tests for all components

**What Phase 1 Does NOT Do**:
- ❌ No real reasoning (placeholder node only)
- ❌ No tool orchestration (tools exist but aren't called)
- ❌ No LLM-powered analysis
- ❌ No report generation

These features come in Phase 2 and 3.

## Architecture Diagram

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│      MedAgent.run(query)            │
│  Creates initial AgentState         │
└──────────────┬──────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│         LangGraph Workflow           │
│                                      │
│   ┌──────────────────────────────┐  │
│   │   query_analysis_node        │  │
│   │   (Phase 1: Placeholder)     │  │
│   │                              │  │
│   │   - Validates query          │  │
│   │   - Logs to reasoning trace  │  │
│   │   - Passes state through     │  │
│   └──────────────────────────────┘  │
│                                      │
│   Future (Phase 2):                  │
│   ├─ planning_node                   │
│   ├─ tool_execution_node             │
│   ├─ synthesis_node                  │
│   ├─ verification_node               │
│   └─ report_generation_node          │
└──────────────┬───────────────────────┘
               │
               ▼
          Final AgentState
     (with reasoning trace,
      tool results, report)
```

## AgentState Structure

The `AgentState` is the **core data structure** that flows through the entire agent. Every piece of information lives in this state.

### Field Categories

#### 1. Input Fields
```python
query: str  # Original user query
```

#### 2. Planning Fields
```python
research_plan: Optional[str]  # Agent's strategy
current_step: int             # Iteration counter
max_iterations: int           # Loop limit
```

#### 3. Tool Usage Fields
```python
tools_to_call: List[str]           # Queue of tools to execute
tool_results: Dict[str, Any]       # Results from each tool
tool_call_history: List[Dict]      # Complete log of API calls
```

#### 4. Reasoning Fields
```python
intermediate_thoughts: List[str]   # Step-by-step reasoning
confidence_score: float            # Self-assessed confidence (0-1)
needs_more_info: bool              # Should agent continue?
```

#### 5. Output Fields
```python
final_report: Optional[str]        # Generated markdown report
citations: List[Dict[str, str]]    # All sources used
```

#### 6. Metadata Fields
```python
start_time: datetime               # When started
total_tokens_used: int             # LLM token count
errors: List[str]                  # Any errors encountered
```

#### 7. LangChain Compatibility
```python
messages: Annotated[List, add_messages]  # Message history
```

### Why This Structure?

**Transparency**: Every step is logged in `intermediate_thoughts`
**Debuggability**: Can inspect state at any point
**Extensibility**: Easy to add new fields in future phases
**Type Safety**: Full type hints prevent errors

## LangGraph Flow

### Phase 1 Flow (Current)

```
START → query_analysis_node → END
```

**What happens**:
1. User calls `agent.run(query)`
2. `create_initial_state()` creates AgentState
3. Graph invokes `query_analysis_node`
4. Node validates query, adds to reasoning trace
5. Graph reaches END
6. Final state returned to user

### Phase 2 Flow (Planned)

```
START → query_analysis → planning → tool_execution
                                         ↓
        report_generation ← verification ← synthesis
                ↓
               END
```

**What will happen**:
- **Query Analysis**: Extract targets, diseases, query type
- **Planning**: Decide which tools to use and in what order
- **Tool Execution**: Call PubMed, ClinicalTrials, ChEMBL
- **Synthesis**: Combine results, cross-reference
- **Verification**: Self-reflect, decide if more research needed
- **Report Generation**: Create final markdown report

Conditional edge at verification:
- If `needs_more_info = True` → Loop back to tool_execution
- If `needs_more_info = False` → Proceed to report

## Key Components

### 1. config/llm_config.py

**Purpose**: Initialize Google Gemini LLM

**Key Function**: `get_llm(temperature, max_tokens, timeout)`

**Features**:
- Loads API key from environment
- Clear error if key missing
- Returns configured ChatGoogleGenerativeAI
- Free tier: 15 req/min, 1500 req/day, 1M token context

**Usage**:
```python
from config.llm_config import get_llm

llm = get_llm(temperature=0.3)
response = llm.invoke("What are EGFR inhibitors?")
```

### 2. agent/state.py

**Purpose**: Define agent state structure

**Key Class**: `AgentState` (TypedDict with all fields)

**Helper**: `create_initial_state(query, max_iterations)`

**Usage**:
```python
from agent.state import create_initial_state

state = create_initial_state("Find EGFR inhibitors")
# state has all fields initialized with defaults
```

### 3. agent/nodes.py

**Purpose**: Individual reasoning nodes

**Phase 1 Node**: `query_analysis_node(state) -> state`

**What it does**:
- Validates query exists
- Logs query
- Adds to reasoning trace
- Passes state through

**Phase 2 will add**:
- `planning_node`: Create research strategy
- `tool_execution_node`: Call APIs
- `synthesis_node`: Combine results
- `verification_node`: Self-reflect
- `report_generation_node`: Generate report

### 4. agent/graph.py

**Purpose**: Orchestrate agent flow

**Key Function**: `build_agent_graph()` - Returns compiled LangGraph

**Key Class**: `MedAgent` - Main interface

**Methods**:
- `run(query)`: Execute research
- `get_reasoning_trace(state)`: Extract thoughts
- `get_tool_usage_stats(state)`: Tool call summary

**Usage**:
```python
from agent.graph import MedAgent

agent = MedAgent(max_iterations=10)
result = agent.run("What are EGFR inhibitors?")

print(result["intermediate_thoughts"])
# ['Query received and validated: What are EGFR inhibitors?']
```

## How LangGraph Works

### Concept

LangGraph is a **state machine framework** for LLMs. Think of it as a flowchart where:
- **Nodes** = Functions that process state
- **Edges** = Transitions between nodes
- **State** = Data that flows through

### Key Principles

1. **State is Immutable**: Nodes don't modify state in-place, they return new state
2. **Explicit Flow**: You define exactly how nodes connect
3. **Conditional Routing**: Can have if/else branching
4. **Loops**: Nodes can point back to earlier nodes

### Phase 1 Example

```python
workflow = StateGraph(AgentState)

# Add a node
workflow.add_node("query_analysis", query_analysis_node)

# Set entry point
workflow.set_entry_point("query_analysis")

# Add edge (transition)
workflow.add_edge("query_analysis", END)

# Compile
graph = workflow.compile()

# Execute
result = graph.invoke(initial_state)
```

### Phase 2 Will Add

```python
# Conditional edge
workflow.add_conditional_edges(
    "verification",
    should_continue_research,  # Decision function
    {
        "continue": "tool_execution",  # Loop back
        "finish": "report_generation"   # End
    }
)
```

## Running Tests

### Quick Test

```bash
cd ~/Documents/MedAgent
source venv/bin/activate
python test_phase1.py
```

### Expected Output

```
======================================================================
MEDAGENT PHASE 1 VALIDATION
Testing: Agent Foundation Setup
======================================================================

======================================================================
TEST: 1. LLM Connection Test
======================================================================
Attempting to connect to Gemini API...
Sending test prompt...
Response: Hello from Gemini!

✓ PASS
  LLM responded: Hello from Gemini!

======================================================================
TEST: 2. Agent Initialization Test
======================================================================
Creating MedAgent instance...
Agent created: MedAgent(max_iterations=5, temperature=0.3)
Graph compiled successfully

✓ PASS
  Agent initialized with compiled graph

======================================================================
TEST: 3. State Flow Test
======================================================================
Creating initial state...
Verifying state structure...
All required fields present
Initial state valid
Running state through query_analysis_node...
Thoughts: ['Query received and validated: Test query for validation']

✓ PASS
  State flows correctly through nodes

======================================================================
TEST: 4. End-to-End Smoke Test
======================================================================
Creating agent...
Running query: What are EGFR inhibitors?

Query: What are EGFR inhibitors?
Steps taken: 0

Reasoning trace (1 steps):
  1. Query received and validated: What are EGFR inhibitors?

Tool stats: {'tools_called': [], 'total_calls': 0, 'successful_calls': 0, 'total_results': 0}

✓ PASS
  Agent executed query successfully

======================================================================
TEST SUMMARY
======================================================================
✓ PASS   | LLM Connection
✓ PASS   | Agent Initialization
✓ PASS   | State Flow
✓ PASS   | End-to-End
======================================================================
Results: 4/4 tests passed

======================================================================
✓ PHASE 1 COMPLETE - Agent foundation is working!
======================================================================

Next steps:
  - Review agent/state.py to understand state structure
  - Review agent/graph.py to understand LangGraph flow
  - Ready for Phase 2: Adding real reasoning and tool orchestration
```

## Troubleshooting

### "GOOGLE_API_KEY not found"

**Problem**: API key not in environment

**Solution**:
1. Check `.env` file exists in project root
2. Ensure line: `GOOGLE_API_KEY=your_actual_key`
3. Get key from: https://makersuite.google.com/app/apikey
4. Restart terminal/reload environment

### "Import Error: No module named 'langgraph'"

**Problem**: Dependencies not installed

**Solution**:
```bash
cd ~/Documents/MedAgent
source venv/bin/activate
pip install -r requirements.txt
```

### "Graph compilation failed"

**Problem**: LangGraph structure issue

**Solution**:
- Check all nodes are defined in `agent/nodes.py`
- Verify edges connect valid nodes
- Check logs in `logs/medagent.log`

## What's Next?

### Phase 2: Agent Intelligence

Will add:
- **Real Query Analysis**: LLM extracts targets, diseases
- **Planning**: Agent decides tool sequence
- **Tool Orchestration**: Actually calls PubMed/ChEMBL/ClinicalTrials
- **Synthesis**: Combines results intelligently
- **Self-Reflection**: Agent evaluates own work
- **Report Generation**: Creates structured markdown

### Phase 3: Evaluation & Tuning

Will add:
- **Test Suite**: 10 benchmark queries
- **Metrics**: Success rate, tool precision, hallucination rate
- **Hyperparameter Tuning**: Find optimal temperature, iterations
- **Human Evaluation**: Manual quality assessment

## Success Criteria

Phase 1 is complete when:

✅ All 4 tests pass in `test_phase1.py`
✅ Can initialize Gemini LLM
✅ AgentState structure defined
✅ LangGraph builds and compiles
✅ Can run `agent.run()` without crashes
✅ Reasoning trace is populated

## Key Takeaways

1. **Phase 1 = Infrastructure**: We built the plumbing, not the intelligence
2. **State is King**: Everything flows through AgentState
3. **LangGraph = Explicit**: No magic, every transition is defined
4. **Placeholder is OK**: query_analysis_node will get real logic in Phase 2
5. **Test First**: Comprehensive tests ensure foundation is solid

---

**Phase 1 Complete!** The agent foundation is ready. Phase 2 will add the intelligence.
