# MedAgent System Architecture

## Overview

MedAgent is built as a multi-layered system with clear separation of concerns. The architecture is designed for extensibility, reliability, and performance.

## Layer Architecture

### 1. External API Layer

The foundation layer consisting of free biomedical APIs:

- **PubMed E-utilities** (`eutils.ncbi.nlm.nih.gov`)
  - Scientific literature database
  - 35+ million citations
  - Free, no authentication required
  - Rate limit: 3 requests/second

- **ClinicalTrials.gov API** (`clinicaltrials.gov/api/v2`)
  - Clinical trial registry
  - 400,000+ studies worldwide
  - Free, no authentication required
  - Rate limit: 10 requests/second (recommended)

- **ChEMBL REST API** (`ebi.ac.uk/chembl/api`)
  - Chemical and bioactivity database
  - 2+ million compounds
  - Free, no authentication required
  - Rate limit: 10 requests/second (recommended)

### 2. Utility Layer

Core utilities providing cross-cutting concerns:

#### Rate Limiter (`utils/rate_limiter.py`)
- **Algorithm**: Token bucket
- **Thread-safe**: Uses threading.Lock
- **Per-API limits**: Separate buckets for each API
- **Usage**: Decorator-based `@rate_limit(key, rate)`

#### Retry Handler (`utils/retry_handler.py`)
- **Strategy**: Exponential backoff with jitter
- **Retryable errors**: Connection, timeout, 429, 500-504
- **Non-retryable**: 400, 401, 403, 404
- **Max retries**: 3 (configurable)
- **Backoff**: base^attempt (default base=2)

#### Logger (`utils/logger.py`)
- **Formats**: JSON (file) + Human-readable (console)
- **Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Structured logging**: Includes tool_name, query, latency_ms, status
- **Dual output**: Console + file (`logs/medagent.log`)

### 3. Tool Layer

API wrapper implementations:

#### Base Tool (`tools/base_tool.py`)
Abstract base class providing:
- **Monitoring**: Automatic latency tracking
- **Caching**: In-memory with TTL (default 1 hour)
- **Error handling**: Consistent error messages
- **Result format**: Standardized ToolResult
- **HTTP session**: RetrySession with automatic retries

#### Tool Implementations

**PubMed Tool** (`tools/pubmed_tool.py`)
- Search by query with date filtering
- Fetch paper details by PMID
- XML parsing (ElementTree)
- Extracts: title, abstract, authors, DOI, journal

**ClinicalTrials Tool** (`tools/clinical_trials_tool.py`)
- Search by condition, intervention, status, phase
- Automatic pagination handling
- JSON parsing
- Extracts: trial details, locations, interventions

**ChEMBL Tool** (`tools/chembl_tool.py`)
- Search by target, indication
- Get drug/compound details
- JSON parsing
- Extracts: compounds, mechanisms, development phase

### 4. Agent Orchestration Layer (Day 2)

Future implementation using LangGraph:
- Query understanding and decomposition
- Multi-step research plans
- Tool selection and orchestration
- Result synthesis
- Conversational memory

### 5. Interface Layer (Day 3)

Future implementation:
- Web UI (Streamlit/Gradio)
- CLI interface
- API endpoints
- Export functionality

## Data Flow

### Single Tool Call Flow

```
User Query
    │
    ▼
Tool.execute()
    │
    ├─► Check cache ──► Cache hit? ──► Return cached result
    │                      │
    │                      ▼ No
    │                   Continue
    ▼
Rate Limiter
    │
    ▼
RetrySession
    │
    ├─► API Request
    │       │
    │       ├─► Success ──► Parse results ──► Cache ──► Return
    │       │
    │       └─► Error ──► Retry? ──► Yes ──► Backoff ──► Retry
    │                       │
    │                       ▼ No
    │                   Handle error
    ▼
Log result (success/error)
    │
    ▼
Return ToolResult
```

### Multi-Agent Flow (Day 2+)

```
User Query
    │
    ▼
LLM Query Understanding
    │
    ▼
Query Decomposition
    │
    ▼
Research Plan Generation
    │
    ▼
Tool Selection & Execution
    │
    ├─► PubMed Tool
    ├─► ClinicalTrials Tool
    └─► ChEMBL Tool
         │
         ▼
    Results Aggregation
         │
         ▼
    Synthesis (LLM)
         │
         ▼
    Final Answer
```

## Design Patterns

### 1. Abstract Factory Pattern
- `BaseTool` as abstract base class
- Concrete tools inherit and implement required methods
- Ensures consistent interface across all tools

### 2. Decorator Pattern
- `@rate_limit` for rate limiting
- `@retry_on_failure` for retry logic
- Clean separation of concerns

### 3. Template Method Pattern
- `_execute_with_monitoring()` in BaseTool
- Defines algorithm skeleton
- Subclasses implement specific steps

### 4. Strategy Pattern
- Different parsing strategies for XML vs JSON
- Tool-specific error handling

## Configuration Management

### Settings (`config/settings.py`)
- **Type**: Pydantic BaseSettings
- **Source**: Environment variables + defaults
- **Validation**: Automatic type checking
- **Scope**: Application-wide singleton

### Environment Variables
- `.env` file for local configuration
- `.env.example` as template
- Secrets not committed to git

## Error Handling Strategy

### Error Categories

1. **Network Errors** (Retryable)
   - ConnectionError
   - Timeout
   - Response: User-friendly message, automatic retry

2. **API Errors** (Partially Retryable)
   - 429 Too Many Requests → Retry
   - 500-504 Server Errors → Retry
   - 400, 404 Client Errors → No retry

3. **Parsing Errors** (Non-retryable)
   - Invalid XML/JSON
   - Missing expected fields
   - Response: Error message, no retry

4. **Validation Errors** (Non-retryable)
   - Invalid input parameters
   - Response: Error message with guidance

### Error Response Format

```python
{
    "success": False,
    "data": None,
    "metadata": {
        "query": "...",
        "timestamp": "...",
        "tool": "...",
        "latency_ms": 123
    },
    "error": "User-friendly error message"
}
```

## Performance Optimizations

### Caching Strategy
- **Type**: In-memory dictionary
- **Key**: Method + parameters hash
- **TTL**: 1 hour (configurable)
- **Eviction**: Time-based expiration
- **Thread-safety**: Not required (GIL)

### Rate Limiting
- **Algorithm**: Token bucket
- **Benefits**: Smooth traffic, burst tolerance
- **Implementation**: Per-API separate buckets

### Connection Pooling
- **Method**: requests.Session
- **Benefits**: Connection reuse, reduced latency
- **Scope**: Per-tool instance

## Security Considerations

### API Keys
- Stored in environment variables
- Never committed to git
- .env in .gitignore

### Input Validation
- Type hints + Pydantic validation
- Query sanitization
- Parameter bounds checking

### Rate Limiting
- Prevents API abuse
- Respects API provider limits
- Protects from accidental DOS

## Scalability Considerations

### Current (Day 1)
- Single-process, synchronous
- In-memory caching
- Suitable for: Single user, research tasks

### Future Enhancements
- **Async I/O**: aiohttp for concurrent requests
- **Distributed caching**: Redis
- **Queue system**: Celery for background tasks
- **Database**: PostgreSQL for persistent storage
- **Containerization**: Docker deployment

## Testing Strategy

### Unit Tests
- Mock external API calls
- Test error handling
- Test rate limiting
- Test caching
- Coverage target: 80%+

### Integration Tests (Future)
- Real API calls (limited)
- End-to-end workflows
- Agent behavior

### Performance Tests (Future)
- Load testing
- Latency benchmarks
- Cache hit rates

## Monitoring & Observability

### Logging
- **Format**: Structured JSON
- **Fields**: timestamp, level, tool, query, latency, status
- **Storage**: File + console
- **Rotation**: Future enhancement

### Metrics (Future)
- API call latency
- Cache hit rate
- Error rates
- Tool usage statistics

## Extensibility

### Adding New Tools
1. Create class inheriting from `BaseTool`
2. Implement `execute()` and `parse_results()`
3. Add rate limiting
4. Write tests
5. Add to `tools/__init__.py`

### Adding New Utilities
1. Create module in `utils/`
2. Add to `utils/__init__.py`
3. Document usage
4. Write tests

### Configuration Changes
1. Add field to `Settings` class
2. Update `.env.example`
3. Document in README

## Dependencies

### Core Dependencies
- **requests**: HTTP client
- **pydantic**: Settings validation
- **python-dotenv**: Environment management

### Agent Framework (Day 2+)
- **langchain**: LLM framework
- **langgraph**: Agent orchestration
- **google-generativeai**: Gemini API

### Testing
- **pytest**: Test framework
- **unittest.mock**: Mocking

### Future
- **aiohttp**: Async HTTP
- **redis**: Distributed caching
- **celery**: Task queue
- **streamlit**: Web UI
