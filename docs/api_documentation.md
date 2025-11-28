# API Documentation

Complete reference for all MedAgent tool APIs.

## PubMed Tool API

### Class: `PubMedTool`

Wrapper for PubMed E-utilities API.

#### Methods

##### `search_pubmed(query, max_results=10, years_back=2, date_from=None, date_to=None)`

Search PubMed for scientific papers.

**Parameters:**
- `query` (str): Search query in PubMed syntax
- `max_results` (int, optional): Maximum results to return (default: 10)
- `years_back` (int, optional): Limit to last N years (default: 2)
- `date_from` (str, optional): Start date in YYYY/MM/DD format
- `date_to` (str, optional): End date in YYYY/MM/DD format

**Returns:** `ToolResult` with list of paper dictionaries

**Paper Dictionary Fields:**
- `pmid`: PubMed ID
- `title`: Paper title
- `abstract`: Abstract text
- `authors`: List of author names
- `pub_date`: Publication date
- `year`: Publication year
- `journal`: Journal name
- `doi`: Digital Object Identifier
- `url`: PubMed URL

**Example:**
```python
pubmed = PubMedTool()
result = pubmed.search_pubmed("EGFR inhibitors", max_results=5)
```

##### `get_paper_details(pmid)`

Get detailed information for a specific paper.

**Parameters:**
- `pmid` (str): PubMed ID

**Returns:** `ToolResult` with paper dictionary

**Example:**
```python
result = pubmed.get_paper_details("12345678")
```

---

## ClinicalTrials Tool API

### Class: `ClinicalTrialsTool`

Wrapper for ClinicalTrials.gov API v2.

#### Methods

##### `search_trials(condition=None, intervention=None, status="RECRUITING", phase=None, max_results=None, sponsor=None, country=None)`

Search for clinical trials.

**Parameters:**
- `condition` (str, optional): Disease or condition (e.g., "lung cancer")
- `intervention` (str, optional): Treatment/drug name (e.g., "pembrolizumab")
- `status` (str, optional): Trial status (default: "RECRUITING")
- `phase` (str, optional): Trial phase (PHASE1, PHASE2, PHASE3, PHASE4)
- `max_results` (int, optional): Maximum results (default: 100)
- `sponsor` (str, optional): Sponsor organization
- `country` (str, optional): Country name

**Valid Status Values:**
- RECRUITING
- NOT_YET_RECRUITING
- ACTIVE_NOT_RECRUITING
- COMPLETED
- SUSPENDED
- TERMINATED
- WITHDRAWN

**Valid Phase Values:**
- EARLY_PHASE1
- PHASE1
- PHASE2
- PHASE3
- PHASE4
- NA

**Returns:** `ToolResult` with list of trial dictionaries

**Trial Dictionary Fields:**
- `nct_id`: ClinicalTrials.gov identifier
- `title`: Trial title
- `status`: Current status
- `phase`: Trial phase
- `conditions`: List of conditions
- `interventions`: List of intervention dictionaries
- `sponsor`: Lead sponsor name
- `locations`: List of trial locations (max 10)
- `enrollment`: Number of participants
- `start_date`: Start date
- `completion_date`: Completion date
- `brief_summary`: Trial summary (max 500 chars)
- `url`: ClinicalTrials.gov URL

**Example:**
```python
ct = ClinicalTrialsTool()
result = ct.search_trials(
    condition="lung cancer",
    intervention="pembrolizumab",
    status="RECRUITING"
)
```

##### `get_trial_details(nct_id)`

Get details for a specific trial.

**Parameters:**
- `nct_id` (str): NCT identifier (e.g., "NCT01234567")

**Returns:** `ToolResult` with trial dictionary

**Example:**
```python
result = ct.get_trial_details("NCT01234567")
```

---

## ChEMBL Tool API

### Class: `ChEMBLTool`

Wrapper for ChEMBL REST API.

#### Methods

##### `search_by_target(target_name, max_results=10)`

Search for compounds targeting a specific protein.

**Parameters:**
- `target_name` (str): Protein target name (e.g., "EGFR", "HER2")
- `max_results` (int, optional): Maximum results (default: 10)

**Returns:** `ToolResult` with list of compound dictionaries

**Compound Dictionary Fields:**
- `chembl_id`: ChEMBL identifier
- `name`: Compound name
- `molecule_type`: Type (e.g., "Small molecule")
- `molecular_weight`: Molecular weight
- `alogp`: Lipophilicity
- `development_phase`: Current phase (Preclinical, Phase 1-4, Approved)
- `max_phase`: Numeric phase (0-4)
- `mechanism_of_action`: Primary mechanism
- `mechanisms`: List of all mechanisms
- `url`: ChEMBL URL

**Example:**
```python
chembl = ChEMBLTool()
result = chembl.search_by_target("EGFR", max_results=5)
```

##### `get_drug_info(chembl_id)`

Get detailed information about a drug/compound.

**Parameters:**
- `chembl_id` (str): ChEMBL ID (e.g., "CHEMBL941")

**Returns:** `ToolResult` with compound dictionary

**Example:**
```python
result = chembl.get_drug_info("CHEMBL941")
```

##### `search_by_indication(disease, max_results=20)`

Search for drugs by disease indication.

**Parameters:**
- `disease` (str): Disease name (e.g., "lung cancer")
- `max_results` (int, optional): Maximum results (default: 20)

**Returns:** `ToolResult` with list of drug indication dictionaries

**Drug Indication Dictionary Fields:**
- `chembl_id`: ChEMBL identifier
- `drug_name`: Drug name
- `indication`: Disease indication
- `max_phase`: Development phase (0-4)
- `efo_term`: Disease ontology term

**Example:**
```python
result = chembl.search_by_indication("lung cancer")
```

---

## Common Response Format

All tools return a `ToolResult` object with the following structure:

```python
class ToolResult:
    success: bool          # True if request succeeded
    data: Any             # Result data (list or dict)
    metadata: dict        # Request metadata
    error: str or None    # Error message if failed
```

### Metadata Fields

- `query`: Original query string
- `timestamp`: ISO 8601 timestamp
- `tool`: Tool name
- `latency_ms`: Request latency in milliseconds
- `results_count`: Number of results
- `cached`: Whether result was from cache (True/False)

### Success Response Example

```python
{
    "success": True,
    "data": [
        {
            "pmid": "12345678",
            "title": "Example Paper",
            # ... more fields
        }
    ],
    "metadata": {
        "query": "EGFR inhibitors",
        "timestamp": "2024-01-01T12:00:00Z",
        "tool": "PubMed",
        "latency_ms": 523,
        "results_count": 1,
        "cached": False
    },
    "error": None
}
```

### Error Response Example

```python
{
    "success": False,
    "data": None,
    "metadata": {
        "query": "invalid query",
        "timestamp": "2024-01-01T12:00:00Z",
        "tool": "PubMed",
        "latency_ms": 123
    },
    "error": "Failed to connect to API. Please check your internet connection."
}
```

---

## Rate Limits

| Tool | Rate Limit | Authentication |
|------|-----------|----------------|
| PubMed | 3 req/sec | Not required |
| ClinicalTrials | 10 req/sec (recommended) | Not required |
| ChEMBL | 10 req/sec (recommended) | Not required |

Rate limiting is automatically enforced by the tools using a token bucket algorithm.

---

## Error Handling

### Error Types

**Retryable Errors (automatic retry with exponential backoff):**
- ConnectionError: Network connectivity issues
- Timeout: Request timeout
- HTTP 429: Too many requests
- HTTP 500-504: Server errors

**Non-retryable Errors (immediate failure):**
- HTTP 400: Bad request (invalid parameters)
- HTTP 401: Unauthorized
- HTTP 403: Forbidden
- HTTP 404: Not found
- HTTP 422: Unprocessable entity
- Parsing errors: Invalid XML/JSON response

### Retry Configuration

- Max retries: 3
- Backoff strategy: Exponential with jitter
- Backoff formula: base^attempt (base=2)
- Max backoff: 60 seconds

---

## Caching

All tools implement automatic caching:

- **Storage**: In-memory dictionary
- **TTL**: 1 hour (configurable)
- **Cache key**: Method name + parameters
- **Behavior**: Exact match only

**Clear cache:**
```python
tool = PubMedTool()
tool.clear_cache()
```

**Get cache stats:**
```python
stats = tool.get_cache_stats()
print(f"Entries: {stats['entries']}")
print(f"Size: {stats['size_bytes']} bytes")
```

---

## Advanced Usage

### Custom Configuration

```python
from config.settings import settings

# Modify settings
settings.PUBMED_RATE_LIMIT = 5
settings.CACHE_TTL = 7200  # 2 hours
settings.MAX_RETRIES = 5
```

### Custom Timeout

```python
pubmed = PubMedTool()
pubmed.timeout = 60  # 60 seconds
```

### Logging

```python
from utils.logger import get_logger

logger = get_logger(__name__)
logger.setLevel("DEBUG")  # Show debug messages
```
