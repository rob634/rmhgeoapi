# Archived Claude Documentation - 05 DEC 2025

**Date Archived**: 05 DEC 2025
**Reason**: Consolidation of docs_claude/ folder to reduce file count and improve navigation

## Consolidated Files

| File | Reason | Merged Into |
|------|--------|-------------|
| APPLICATION_INSIGHTS_QUERY_PATTERNS.md | Comprehensive query patterns | DEPLOYMENT_GUIDE.md |
| claude_log_access.md | Authentication and access guide | DEPLOYMENT_GUIDE.md |
| MANAGED_IDENTITY_QUICKSTART.md | Quick setup guide | DEPLOYMENT_GUIDE.md |
| FILE_CATALOG.md | Outdated (29 OCT 2025), ~542 lines | CLAUDE_CONTEXT.md has current structure |

## What Was Consolidated

### Into DEPLOYMENT_GUIDE.md (now comprehensive ops guide):
- **Application Insights Logging** section with:
  - Bearer token authentication pattern
  - Copy-paste ready query scripts
  - Common KQL queries (errors, retries, task processing)
  - Azure Functions severity mapping bug workaround
- **Managed Identity Authentication** section with:
  - Quick setup steps (enable identity, setup PostgreSQL, configure settings)
  - Local development options (az login vs password fallback)
  - Verification commands

### Structure After Consolidation

**docs_claude/** now has 10 files (was 14):
- CLAUDE_CONTEXT.md - Entry point
- TODO.md - Active tasks only
- HISTORY.md - Completed work (older)
- HISTORY2.md - Completed work (recent)
- DEPLOYMENT_GUIDE.md - Ops, logging, identity, troubleshooting
- ARCHITECTURE_REFERENCE.md - Deep technical specs
- SCHEMA_ARCHITECTURE.md - PostgreSQL 5-schema design
- SERVICE_BUS_HARMONIZATION.md - Queue configuration
- COREMACHINE_PLATFORM_ARCHITECTURE.md - Two-layer design
- JOB_CREATION_QUICKSTART.md - New job creation guide

## Current Documentation

For current documentation, see:
- `docs_claude/DEPLOYMENT_GUIDE.md` - Consolidated operations guide
- `docs_claude/CLAUDE_CONTEXT.md` - Project structure overview
