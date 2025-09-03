# Database Monitoring Enhancement Plan

**Date**: September 3, 2025  
**Author**: Claude Code Assistant  
**Purpose**: Implement comprehensive database monitoring endpoints for production troubleshooting

## Overview

Current system has complete PostgreSQL infrastructure but lacks accessible database query endpoints for monitoring when DBeaver access is blocked by network restrictions. This plan adds production-ready database diagnostics to the existing function app.

## Current Database Infrastructure Analysis

### ✅ EXISTING COMPONENTS
- **PostgreSQL Schema**: Complete jobs/tasks tables with atomic functions (`schema_postgres.sql`)
- **Health Endpoint**: `/api/health` with component validation (`trigger_health.py`)
- **Database Adapter**: PostgreSQL backend with managed identity (`adapter_storage.py`)
- **Schema Manager**: Database validation and setup (`service_schema_manager.py`)
- **Configuration**: Strongly typed PostgreSQL config (`config.py`)
- **Repository Layer**: Data access patterns with completion detection (`repository_data.py`)

### 🎯 IDENTIFIED GAPS
1. No dedicated DB query endpoints for external monitoring
2. Health endpoint doesn't expose database query results (only validation status)
3. Missing production-ready DB diagnostics for troubleshooting task failures
4. No job/task status query endpoints accessible without DBeaver
5. Limited error investigation capabilities for production debugging

## Implementation Plan

### Phase 1: Enhanced Health Endpoint (30 min)
**Extend existing `/api/health` with database query results**

**TODO:**
- [ ] Modify `trigger_health.py` to include database query metrics
- [ ] Add PostgreSQL connection test with query timing measurement
- [ ] Include recent job counts and status breakdown (last 24h)
- [ ] Add task processing metrics (queued, processing, completed, failed)
- [ ] Expose database function availability check with test execution
- [ ] Add query performance metrics (avg response time)

**Expected Output Example:**
```json
{
  "status": "healthy",
  "components": {
    "database": {
      "status": "healthy",
      "connection_time_ms": 45,
      "jobs_last_24h": {
        "total": 156,
        "completed": 134,
        "processing": 8,
        "failed": 14
      },
      "tasks_last_24h": {
        "total": 623,
        "completed": 598,
        "processing": 12,
        "failed": 13
      },
      "functions_available": ["complete_task_and_check_stage", "advance_job_stage", "check_job_completion"],
      "avg_query_time_ms": 12
    }
  }
}
```

### Phase 2: Database Query Endpoints (45 min)
**Create dedicated monitoring endpoints for database access**

**TODO:**
- [ ] Create `trigger_db_query.py` - Base database query HTTP trigger
- [ ] Implement `/api/db/jobs?limit=10&status=processing&hours=24` endpoint
  - Query recent jobs with filtering by status and time range
  - Include job parameters and stage information
  - Support pagination and sorting
- [ ] Implement `/api/db/tasks/{job_id}` endpoint
  - Query all tasks for a specific job ID
  - Include task status, parameters, results, and error details
  - Show stage progression and completion status
- [ ] Implement `/api/db/stats` endpoint
  - Database statistics and health metrics
  - Table sizes, index usage, query performance
  - Recent activity patterns and trends
- [ ] Implement `/api/db/functions/test` endpoint
  - Test PostgreSQL function execution with sample data
  - Validate atomic completion functions
  - Performance testing of stored procedures
- [ ] Add proper error handling and logging for all endpoints
- [ ] Implement query parameter validation and sanitization

**Expected Endpoints:**
```
GET /api/db/jobs?limit=10&status=processing&hours=24
GET /api/db/jobs/{job_id}
GET /api/db/tasks/{job_id}
GET /api/db/tasks?status=failed&limit=20
GET /api/db/stats
GET /api/db/functions/test
```

### Phase 3: Enhanced Error Investigation (30 min)
**Add task failure analysis and troubleshooting endpoints**

**TODO:**
- [ ] Implement `/api/db/errors?hours=24&limit=50` endpoint
  - Recent error patterns and failure analysis
  - Group errors by type and frequency
  - Include error details and stack traces
- [ ] Implement `/api/db/poison?limit=20` endpoint
  - Poison queue analysis and problematic jobs
  - Jobs with multiple retry attempts
  - Tasks stuck in processing state
- [ ] Implement `/api/db/performance` endpoint
  - Query performance metrics and slow queries
  - Database resource usage patterns
  - Stage completion timing analysis
- [ ] Create `/api/db/debug/{job_id}` endpoint
  - Comprehensive job debugging information
  - Complete task history and state transitions
  - Timeline of job execution with bottlenecks
- [ ] Add correlation with Application Insights logs
- [ ] Include recommendations for common issues

**Expected Debug Output Example:**
```json
{
  "job_id": "abc123...",
  "debug_info": {
    "job_status": "processing",
    "current_stage": 1,
    "total_stages": 2,
    "tasks": [
      {
        "task_id": "task_1",
        "status": "failed",
        "error": "Task processing logic failure",
        "retry_count": 3,
        "last_heartbeat": "2025-09-03T16:45:00Z"
      }
    ],
    "bottlenecks": ["Task execution logic"],
    "recommendations": ["Check task processing error logs"]
  }
}
```

### Phase 4: Deploy and Test (15 min)
**Deploy and validate functionality**

**TODO:**
- [ ] Update `function_app.py` with new route registrations
- [ ] Deploy to rmhgeoapibeta function app
- [ ] Test all endpoints with real production data
- [ ] Validate network accessibility bypasses DBeaver restrictions
- [ ] Performance test query response times
- [ ] Document endpoint usage and examples
- [ ] Create monitoring dashboard URLs for bookmarking
- [ ] Test error handling and edge cases

## Technical Implementation Details

### Database Query Architecture
```python
# New base class for database query endpoints
class DatabaseQueryTrigger(BaseHttpTrigger):
    """Base class for database monitoring endpoints."""
    
    def __init__(self, endpoint_name: str):
        super().__init__(endpoint_name)
        self.repository = DataRepository()
    
    def execute_safe_query(self, query: str, params: dict) -> dict:
        """Execute database query with error handling and logging."""
        # Implementation with timeout, error handling, logging
```

### Security Considerations
- [ ] Implement query parameter validation to prevent SQL injection
- [ ] Add rate limiting for database query endpoints
- [ ] Sanitize sensitive data in query results (passwords, keys)
- [ ] Add authentication/authorization if needed for production
- [ ] Log all database access for audit trails

### Performance Considerations
- [ ] Implement query result caching for expensive operations
- [ ] Add query timeout protection (max 30 seconds)
- [ ] Optimize database queries with proper indexing
- [ ] Limit result set sizes to prevent memory issues
- [ ] Add query performance monitoring

## Expected Benefits

### Immediate Benefits
- **Network-independent database access** - No more DBeaver blocking issues
- **Real-time job monitoring** - Live status without database tools
- **Enhanced troubleshooting** - Direct access to error patterns and job states
- **Production diagnostics** - Comprehensive health and performance metrics

### Long-term Benefits
- **Proactive monitoring** - Early detection of issues through automated queries
- **Performance optimization** - Database performance insights and bottleneck identification
- **Operational efficiency** - Faster debugging and issue resolution
- **Scalability insights** - Understanding of system behavior under load

## Testing Strategy

### Unit Testing
- [ ] Test database query functions with mock data
- [ ] Validate error handling for connection failures
- [ ] Test parameter validation and sanitization

### Integration Testing
- [ ] Test endpoints with real PostgreSQL database
- [ ] Validate cross-component integration (health + queries)
- [ ] Test under various network conditions

### Performance Testing
- [ ] Measure query response times under load
- [ ] Test concurrent access to database endpoints
- [ ] Validate memory usage with large result sets

## Rollback Plan

If issues arise during implementation:
- [ ] Revert `function_app.py` route changes
- [ ] Remove new trigger files
- [ ] Restore original health endpoint functionality
- [ ] Document lessons learned for future attempts

## Success Metrics

- [ ] All database endpoints respond within 30 seconds
- [ ] Health endpoint includes comprehensive database metrics
- [ ] Error investigation reduces debugging time by 50%
- [ ] Network restrictions no longer block database monitoring
- [ ] Zero SQL injection vulnerabilities in production

---

**Total Estimated Time: 2 hours**  
**Priority: High** (Addresses critical production monitoring gap)  
**Dependencies: None** (All required infrastructure already exists)

## Next Steps

1. Review and approve this plan
2. Begin implementation with Phase 1 (Enhanced Health Endpoint)
3. Iteratively deploy and test each phase
4. Monitor production usage and gather feedback
5. Optimize based on real-world usage patterns

---

*This plan leverages existing infrastructure and follows established patterns in the codebase while addressing the critical need for accessible database monitoring in production environments.*