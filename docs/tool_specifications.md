# Tool Specifications

Detailed technical specifications for each MedAgent tool.

## Design Principles

All tools follow these core principles:

1. **Standardized Interface**: Inherit from `BaseTool`
2. **Automatic Retry**: Transient failures handled automatically
3. **Rate Limiting**: API limits enforced transparently
4. **Caching**: Results cached with TTL
5. **Error Handling**: Graceful degradation with user-friendly messages
6. **Logging**: Structured logging for all operations
7. **Type Safety**: Full type hints

## PubMed Tool Specification

### API Details

**Base URL**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

**Endpoints Used:**
- `esearch.fcgi` - Search for PMIDs
- `efetch.fcgi` - Fetch paper details

**Response Format**: XML

**Authentication**: None required

### Implementation Details

**Rate Limiting:**
- Limit: 3 requests/second
- Implementation: Token bucket with decorator
- Decorator: `@rate_limit("pubmed", 3)`

**Search Process:**
1. Call `esearch.fcgi` to get PMIDs
2. Call `efetch.fcgi` to get paper details
3. Parse XML response
4. Return structured data

**XML Parsing:**
- Library: `xml.etree.ElementTree`
- Handles: Structured abstracts, multiple authors, missing fields
- Fallbacks: Provides "N/A" for missing data

**Date Filtering:**
- Default: Last 2 years
- Format: YYYY/MM/DD
- Parameters: `mindate`, `maxdate`

### Error Scenarios

| Error | Handling |
|-------|----------|
| No results | Return empty list, success=True |
| Invalid XML | Raise ValueError, success=False |
| Network error | Retry 3x with backoff |
| Rate limit | Wait for token, automatic |

### Performance

- **Average latency**: 500-1000ms (2 API calls)
- **Cache hit latency**: <10ms
- **Max results per call**: Configurable (default: 10)

---

## ClinicalTrials Tool Specification

### API Details

**Base URL**: `https://clinicaltrials.gov/api/v2/`

**Endpoints Used:**
- `studies` - Search and retrieve studies

**Response Format**: JSON

**Authentication**: None required

### Implementation Details

**Rate Limiting:**
- Limit: 10 requests/second (recommended)
- Implementation: Token bucket with decorator
- Decorator: `@rate_limit("clinical_trials", 10)`

**Search Process:**
1. Build query from parameters
2. Call API with filters
3. Handle pagination if needed
4. Parse JSON response
5. Return structured data

**Pagination:**
- Page size: 100 studies
- Token-based pagination
- Automatic handling for large result sets

**Filtering:**
- Status: RECRUITING, COMPLETED, etc.
- Phase: PHASE1, PHASE2, PHASE3, PHASE4
- Condition: Free text search
- Intervention: Free text search
- Country: Exact match
- Sponsor: Free text search

### Query Building

Queries use the AREA syntax:
```
AREA[ConditionSearch]lung cancer AND AREA[InterventionSearch]pembrolizumab
```

### Error Scenarios

| Error | Handling |
|-------|----------|
| No results | Return empty list, success=True |
| Invalid JSON | Raise ValueError, success=False |
| Network error | Retry 3x with backoff |
| Invalid status | Silently ignore, use defaults |

### Performance

- **Average latency**: 800-1500ms
- **Cache hit latency**: <10ms
- **Max results per page**: 100
- **Pagination overhead**: ~500ms per additional page

---

## ChEMBL Tool Specification

### API Details

**Base URL**: `https://www.ebi.ac.uk/chembl/api/data/`

**Endpoints Used:**
- `target/search.json` - Search targets
- `target/{id}.json` - Get target details
- `molecule.json` - Search molecules
- `molecule/{id}.json` - Get molecule details
- `drug_indication.json` - Search by indication

**Response Format**: JSON

**Authentication**: None required

### Implementation Details

**Rate Limiting:**
- Limit: 10 requests/second (recommended)
- Implementation: Token bucket with decorator
- Decorator: `@rate_limit("chembl", 10)`

**Search by Target Process:**
1. Search for target by name
2. Extract ChEMBL target ID
3. Query molecules for that target
4. Parse and return results

**Search by Indication Process:**
1. Query drug_indication endpoint
2. Filter by MeSH heading
3. Parse and return results

**Development Phase Mapping:**
```python
{
    0: "Preclinical",
    1: "Phase 1",
    2: "Phase 2",
    3: "Phase 3",
    4: "Approved"
}
```

### Error Scenarios

| Error | Handling |
|-------|----------|
| Target not found | Return empty list, success=True |
| Invalid ChEMBL ID | HTTP 404, return error |
| Network error | Retry 3x with backoff |
| Invalid JSON | Raise ValueError, success=False |

### Performance

- **Average latency**: 1000-2000ms (target search: 2 API calls)
- **Cache hit latency**: <10ms
- **Single molecule lookup**: 500-800ms

---

## Common Tool Features

### Base Tool Class

All tools inherit from `BaseTool` which provides:

**Attributes:**
- `name`: Tool identifier
- `base_url`: API endpoint
- `rate_limit`: Requests per second
- `logger`: Structured logger
- `session`: RetrySession instance
- `cache`: In-memory cache dictionary

**Methods:**
- `execute()`: Main entry point (abstract)
- `parse_results()`: Parse API response (abstract)
- `handle_errors()`: Convert exceptions to messages
- `clear_cache()`: Clear tool cache
- `get_cache_stats()`: Get cache statistics

**Private Methods:**
- `_execute_with_monitoring()`: Execute with timing and logging
- `_get_cache_key()`: Generate cache key
- `_get_from_cache()`: Retrieve from cache
- `_save_to_cache()`: Store in cache

### HTTP Session

All tools use `RetrySession`:

**Features:**
- Automatic retries with exponential backoff
- Connection pooling
- Timeout handling
- Status code checking

**Configuration:**
- Default timeout: 30 seconds
- Max retries: 3
- Backoff base: 2
- Max backoff: 60 seconds

### Logging

Every API call logs:
- Tool name
- Query string
- Latency (ms)
- Status (success/error)
- Error message (if failed)
- Cache status (if applicable)

**Log Formats:**
- Console: Human-readable with colors
- File: Structured JSON

### Caching Strategy

**Cache Key Format:**
```
{method_name}:{param1}={value1}&{param2}={value2}
```

**Example:**
```
search_pubmed:query=EGFR inhibitors&max_results=10
```

**Expiration:**
- TTL: 1 hour (3600 seconds)
- Checked on retrieval
- Expired entries removed lazily

**Thread Safety:**
- Not required (Python GIL)
- Single-threaded access assumed

---

## Testing Specifications

### Unit Test Coverage

Each tool must have tests for:

1. **Basic functionality**
   - Successful API call
   - Result parsing
   - Data structure validation

2. **Error handling**
   - No results
   - Invalid input
   - Network errors
   - Timeout errors
   - API errors (4xx, 5xx)

3. **Rate limiting**
   - Verify rate limit applied
   - Measure delay

4. **Caching**
   - Cache miss (first call)
   - Cache hit (second call)
   - Cache expiration

5. **Parsing**
   - Valid responses
   - Malformed responses
   - Missing fields
   - Empty results

### Mocking Strategy

- Mock HTTP responses
- Don't hit real APIs in unit tests
- Use fixtures for common responses
- Test error conditions with exceptions

### Integration Tests (Future)

- Real API calls (limited)
- End-to-end workflows
- Performance benchmarks

---

## Extension Guidelines

### Adding a New Tool

**Required Steps:**

1. **Create tool class**
   ```python
   from tools.base_tool import BaseTool, ToolResult
   from utils.rate_limiter import rate_limit

   class NewTool(BaseTool):
       def __init__(self):
           super().__init__(
               name="NewTool",
               base_url="https://api.example.com/",
               rate_limit=10
           )
   ```

2. **Implement abstract methods**
   ```python
   def parse_results(self, raw_data):
       # Parse API response
       return parsed_data

   def execute(self, query, **kwargs):
       # Main logic
       return self._execute_with_monitoring(...)
   ```

3. **Add rate limiting**
   ```python
   @rate_limit("new_tool", 10)
   def _api_call(self, params):
       response = self.session.get(url, params=params)
       return response.json()
   ```

4. **Write tests**
   - Create `tests/test_new_tool.py`
   - Mock API responses
   - Test all scenarios

5. **Add examples**
   - Create `examples/test_new_tool.py`
   - Demonstrate usage

6. **Update documentation**
   - Add to README.md
   - Document in api_documentation.md
   - Add to this file

**Best Practices:**

- Use type hints
- Write docstrings
- Handle errors gracefully
- Log operations
- Cache results
- Follow PEP 8

---

## Performance Benchmarks

### Target Latencies (without cache)

| Tool | Operation | Target Latency |
|------|-----------|----------------|
| PubMed | Search (10 results) | <1000ms |
| PubMed | Get paper details | <500ms |
| ClinicalTrials | Search (100 results) | <1500ms |
| ClinicalTrials | Get trial details | <800ms |
| ChEMBL | Search by target (10 results) | <2000ms |
| ChEMBL | Get drug info | <800ms |
| ChEMBL | Search by indication (20 results) | <1500ms |

### Cache Performance

| Metric | Target |
|--------|--------|
| Cache hit latency | <10ms |
| Cache hit rate (typical) | >50% |
| Cache memory usage | <100MB |

### Rate Limit Compliance

All tools must maintain:
- 100% compliance with API rate limits
- No 429 errors under normal operation
- Smooth request distribution (token bucket)
