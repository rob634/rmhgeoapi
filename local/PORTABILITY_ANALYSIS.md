# Container Analysis Portability Review
**Date**: 4 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Current State: Local Script

**File**: `local/analyze_container_contents.py`

### Portability Issues Identified

#### 1. ❌ **Pandas Dependency**
**Problem**: Pandas is HEAVY (100+ MB) and not in Azure Functions requirements
```python
import pandas as pd  # Line 16
df = pd.DataFrame(rows)  # Line 152
```

**Impact**:
- Adds ~100MB to deployment package
- Slower cold starts
- Not necessary for core analysis

**Solution**: Replace with native Python data structures (dicts, lists)

---

#### 2. ❌ **HTTP Requests to Self**
**Problem**: Uses `requests` library to fetch from API endpoints
```python
response = requests.get(self.job_url)  # Line 39
response = requests.get(f"{self.tasks_url}?limit={limit}")  # Line 46
```

**Impact**:
- In Azure Functions, this would be calling itself over HTTP (inefficient)
- Should call repositories directly

**Solution**: Inject repository dependencies instead of HTTP calls

---

#### 3. ❌ **File I/O Assumptions**
**Problem**: Assumes local filesystem for output
```python
OUTPUT_DIR = Path(__file__).parent / "output"  # Line 23
self.output_dir.mkdir(parents=True, exist_ok=True)  # Line 34
```

**Impact**:
- Azure Functions have limited/ephemeral filesystem
- Output should go to Blob Storage or return as JSON

**Solution**:
- Option 1: Return analysis as structured dict/JSON
- Option 2: Save to Azure Blob Storage

---

#### 4. ❌ **Print Statements for Output**
**Problem**: Uses `print()` throughout for results
```python
print(f"📊 Fetching job info for {job_id[:16]}...")  # Line 38
print("\n📦 Stage 2 Blob Analysis ({len(stage2)} blobs):")  # Line 249
```

**Impact**:
- Works for CLI but not for API endpoints
- Need structured JSON response

**Solution**: Use logging + return structured data

---

#### 5. ⚠️ **CLI-Specific Entry Point**
**Problem**: Main function expects command-line args
```python
if len(sys.argv) < 2:  # Line 258
    print("Usage: python analyze_container_contents.py <job_id>")
```

**Impact**: Won't work as imported module in Azure Functions

**Solution**: Separate CLI wrapper from core analysis logic

---

## Recommended Architecture for Azure Functions

### Phase 1: Extract Core Logic (Pure Python)

Create `services/container_analysis.py`:

```python
class ContainerAnalysisService:
    """Pure analysis logic - no I/O, no pandas, no HTTP."""

    def __init__(self, job_repository, task_repository):
        self.job_repo = job_repository
        self.task_repo = task_repository

    def analyze_job(self, job_id: str) -> Dict[str, Any]:
        """
        Analyze container job - returns structured dict.

        Returns:
        {
            'summary': {...},
            'file_categories': {...},
            'patterns': {...},
            'duplicates': {...},
            'timing': {...}
        }
        """
        # Fetch from repositories (not HTTP)
        tasks = self.task_repo.get_tasks_by_job(job_id)

        # Analysis logic (no pandas, pure Python)
        return self._analyze_tasks(tasks)

    def _analyze_tasks(self, tasks: List[Dict]) -> Dict:
        """Core analysis - just dicts and lists."""
        categories = self._categorize_files(tasks)
        patterns = self._detect_patterns(tasks)
        duplicates = self._find_duplicates(tasks)

        return {
            'file_categories': categories,
            'patterns': patterns,
            'duplicates': duplicates,
            'summary': self._create_summary(categories, patterns)
        }
```

### Phase 2: Azure Function Trigger

Create `triggers/analyze_container.py`:

```python
@app.route(route="analysis/container/{job_id}", methods=["GET"])
def analyze_container_contents(req: func.HttpRequest) -> func.HttpResponse:
    """
    Analyze container contents job.

    GET /api/analysis/container/{job_id}

    Query params:
        ?format=json|summary  (default: summary)
        ?save_blob=true       (optional: save to blob storage)
    """
    job_id = req.route_params.get('job_id')
    format_type = req.params.get('format', 'summary')

    # Use repository pattern (not HTTP calls)
    repos = RepositoryFactory.create_repositories()

    # Create service
    service = ContainerAnalysisService(
        job_repository=repos['job_repo'],
        task_repository=repos['task_repo']
    )

    # Run analysis
    results = service.analyze_job(job_id)

    # Optional: Save to blob storage
    if req.params.get('save_blob') == 'true':
        blob_service = BlobService(repos['blob_repo'])
        blob_service.save_analysis(job_id, results)

    # Format response
    if format_type == 'summary':
        return func.HttpResponse(
            _format_summary_text(results),
            mimetype="text/plain"
        )
    else:
        return func.HttpResponse(
            json.dumps(results, default=str),
            mimetype="application/json"
        )
```

### Phase 3: Keep Local CLI Wrapper

Keep `local/analyze_container_contents.py` as thin wrapper:

```python
"""
Local CLI tool - uses HTTP API for convenience.
For production, use services/container_analysis.py directly.
"""

class LocalAnalyzer:
    """Local development tool - fetches via HTTP API."""

    def __init__(self, job_id: str, api_base_url: str):
        self.job_id = job_id
        self.api_url = f"{api_base_url}/api/analysis/container/{job_id}"

    def run(self):
        """Fetch analysis from API and display locally."""
        response = requests.get(self.api_url, params={'format': 'json'})
        data = response.json()

        # Pretty print for CLI
        self._print_summary(data)

        # Save locally
        self._save_local_files(data)
```

---

## Migration Plan

### ✅ **Step 1: Create Pure Analysis Service** (No I/O)
- Extract all analysis logic to `services/container_analysis.py`
- Remove pandas dependency (use native Python)
- No HTTP, no file I/O, no print statements
- Pure functions that take dicts/lists, return dicts/lists

### ✅ **Step 2: Create Azure Function Endpoint**
- New trigger: `triggers/analyze_container.py`
- Uses repository pattern (direct DB access)
- Returns JSON or formatted text
- Optional blob storage for large results

### ✅ **Step 3: Refactor Local Script**
- Keep as thin wrapper around HTTP API
- Good for local development/testing
- Can eventually call service directly for speed

### ✅ **Step 4: Add Unit Tests**
- Test service logic independently
- Mock repositories
- No HTTP/DB required for tests

---

## Benefits of This Approach

1. **Separation of Concerns**
   - Core logic in `services/` (portable, testable)
   - API endpoints in `triggers/` (Azure-specific)
   - CLI tools in `local/` (development)

2. **No Heavy Dependencies**
   - Remove pandas (100+ MB)
   - Native Python is fast and lightweight

3. **Direct Database Access**
   - No HTTP round-trips to self
   - Use existing repository pattern

4. **Reusable Service**
   - Can be called from other jobs
   - Can be used in batch processing
   - Can trigger from queue messages

5. **Testable**
   - Pure functions with mocked repos
   - No external dependencies in tests

---

## Immediate Next Steps

1. **Extract categorization logic** → `services/container_analysis.py`
   - `categorize_file_type()`
   - `detect_patterns()`
   - `find_duplicates()`

2. **Remove pandas** → Use native Python
   - Replace `DataFrame` with `List[Dict]`
   - Use list comprehensions for filtering
   - Use `collections.defaultdict` for grouping

3. **Create service class** → Repository-based
   - Inject `IJobRepository` and `ITaskRepository`
   - Return structured dict (not printed output)

4. **Add Azure Function trigger** → New endpoint
   - `GET /api/analysis/container/{job_id}`
   - Returns JSON by default
   - Optional text summary format

Would you like me to start with Step 1 - creating the portable service class?
