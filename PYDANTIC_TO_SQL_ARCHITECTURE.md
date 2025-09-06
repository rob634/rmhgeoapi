# Pydantic to SQL Dynamic Schema Generation Architecture

**Date**: September 6, 2025  
**Author**: Claude Code Assistant  
**Status**: Phase 1 Implementation - Hardening Required  
**Last Updated**: September 6, 2025

## Overview

This document outlines the architecture for generating PostgreSQL DDL from Pydantic models, making Python models the single source of truth for database schema.

## Core Architecture

```
Pydantic Models (source of truth)
        ↓
Schema Introspector (analyzes models)
        ↓
SQL Generator (creates DDL)
        ↓
Schema Deployer (applies to DB)
        ↓
Validation Loop (verifies deployment)
```

## Implementation Phases

### Phase 1: Basic Generation (Current - In Progress)
- Generate tables from JobRecord, TaskRecord
- Generate ENUMs from JobStatus, TaskStatus  
- Generate standard indexes
- **Keep functions as static templates** (decision deferred)
- Simple deployment via health check

### Phase 2: Smart Constraints (Future)
- Extract validation rules → CHECK constraints
- Generate foreign keys from relationships
- Auto-create indexes based on query patterns
- Add migration tracking

### Phase 3: Full Dynamic (Future)
- Function generation from decorators (TBD)
- Two-way sync (DB changes → Models)
- Version control with migrations
- Multi-environment support

## Key Components

### A. Model Introspector
- Scan all Pydantic models
- Extract field types, constraints, relationships
- Detect ENUMs, foreign keys, indexes needed

### B. SQL Generator
- Type mapping (Python → PostgreSQL)
- Table generation from models
- Constraint generation from validators
- Index generation from access patterns

### C. Function Manager (Phase 1 Decision)
**Deferred Decision - Options:**
1. **Static templates** (current approach for Phase 1)
2. Generate from Python signatures
3. Hybrid - signatures from Python, bodies from templates

### D. Schema Deployer
- Compare generated vs current schema
- Apply changes safely
- Rollback capability

## Proposed File Structure

```
rmhgeoapi/
├── schema_generation/
│   ├── __init__.py
│   ├── introspector.py      # Model analysis
│   ├── sql_generator.py     # DDL generation
│   ├── type_mapper.py       # Type conversions
│   ├── function_templates.py # SQL function templates
│   └── deployer.py          # Schema deployment
│
├── generated/
│   ├── schema_current.sql   # Latest generated
│   ├── schema_backup.sql    # Previous version
│   └── migrations/          # Change history
│
└── models/
    ├── schema_core.py       # Source of truth
    └── model_core.py        # Business models
```

## Phase 1 Implementation Details

### What Gets Generated
- ✅ **Tables**: Direct from Pydantic models
- ✅ **ENUMs**: From Enum subclasses
- ✅ **Constraints**: From field validators
- ✅ **Indexes**: From naming patterns
- ⚠️ **Functions**: Static templates (for now)

### Type Mapping

| Python Type | PostgreSQL Type |
|------------|----------------|
| str | VARCHAR |
| int | INTEGER |
| float | DOUBLE PRECISION |
| bool | BOOLEAN |
| datetime | TIMESTAMP |
| Dict/dict | JSONB |
| List/list | JSONB |
| Enum | Custom ENUM type |

### Constraint Generation

| Pydantic Feature | PostgreSQL Constraint |
|-----------------|---------------------|
| Field(max_length=N) | VARCHAR(N) |
| Field(ge=0) | CHECK (field >= 0) |
| Optional[T] | NULL allowed |
| Required field | NOT NULL |
| Field(regex=...) | CHECK constraint |

### Index Strategy

| Field Pattern | Index Type |
|--------------|-----------|
| Primary key | PRIMARY KEY |
| Foreign key | INDEX on FK column |
| status fields | INDEX for filtering |
| timestamp fields | INDEX for sorting |
| Partial conditions | Partial INDEX |

## Benefits

1. **Single Source of Truth**: Python models only
2. **Type Safety**: Pydantic validation = DB constraints
3. **Refactoring Safety**: Change model → DB follows
4. **Documentation**: Models self-document schema
5. **Testing**: Test models, not SQL

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Complex SQL functions | Keep as templates (Phase 1) |
| PostgreSQL-specific features | Support common features only |
| Performance tuning | Allow manual index additions |
| Migration complexity | Start with regeneration approach |

## Configuration

```python
class SchemaConfig(BaseModel):
    dynamic_generation: bool = False
    auto_deploy: bool = False
    backup_before_deploy: bool = True
    validate_generated: bool = True
    function_generation: str = "template"  # template|decorator|hybrid
```

## Example Usage

```python
# Generate schema from models
generator = SchemaGenerator()
sql = generator.generate_from_models([JobRecord, TaskRecord])

# Deploy to database
deployer = SchemaDeployer()
result = deployer.deploy(sql, dry_run=True)  # Test first
if result.safe:
    deployer.deploy(sql, dry_run=False)  # Actually deploy
```

## Decision Points

### Resolved
- ✅ Scope: Tables and enums first, functions static
- ✅ Timing: Manual trigger via admin endpoint
- ✅ Safety: Dry-run mode first
- ✅ Migration: Regenerate for now

### Pending (Post Phase 1)
- Function generation strategy
- Multi-environment deployment
- Change tracking approach
- Rollback mechanisms

## Migration Path

1. **Start**: Keep existing SQL as backup
2. **Generate**: Create `schema_generated.sql`
3. **Compare**: Diff with `schema_postgres.sql`
4. **Test**: Deploy to test environment
5. **Switch**: Make generated version primary

## Phase 1 Deliverables

1. Basic SQL generator from Pydantic models
2. Tables and ENUMs generation
3. Standard indexes
4. Static function templates
5. Manual deployment trigger
6. Comparison tool for validation

## Success Criteria

- Generated schema matches current static schema
- No manual SQL editing needed for tables/enums
- Functions remain working (static for now)
- Easy to revert if issues arise

## Phase 1 Hardening TODO (Priority Order)

### 🚨 Critical Issues to Fix

1. **DO Block Parsing Errors**
   - **Problem**: String concatenation causes parsing failures for ENUM creation
   - **Solution**: Implement psycopg.sql for injection-safe SQL composition
   - **Impact**: Eliminates deployment errors, cleaner execution

2. **Parameter Name Mismatch**
   - **Problem**: `stage_result` vs `stage_results` inconsistency
   - **Solution**: Standardize to `stage_results` across all functions
   - **Impact**: Fixes job advancement failures

3. **BIGINT Type Casting**
   - **Problem**: Integer literals return as INTEGER not BIGINT
   - **Solution**: Add explicit `::BIGINT` casting in functions
   - **Impact**: Prevents type mismatch errors

### 🔧 SQL Generation Improvements

4. **Implement psycopg.sql Module**
   ```python
   # Replace string concatenation with:
   from psycopg import sql
   query = sql.SQL("CREATE TABLE {}.{} ({})").format(
       sql.Identifier(schema),
       sql.Identifier(table_name),
       sql.SQL(columns)
   )
   ```
   - **Benefits**: Injection-safe, proper escaping, better parsing

5. **Enhanced Constraint Extraction**
   - Extract Pydantic Field constraints → SQL CHECK constraints
   - Map Field(ge=X) → CHECK (field >= X)
   - Map Field(regex=X) → CHECK (field ~ 'X')
   - Map Field(max_length=X) → VARCHAR(X)
   - **Impact**: Database enforces same validation as Python

6. **Proper Optional Type Handling**
   - Detect Optional[T] types correctly
   - Generate NULL/NOT NULL appropriately
   - Default values from Field(default=X)
   - **Impact**: Accurate nullability constraints

### 📊 Validation & Testing

7. **Add Schema Validation Layer**
   - Verify generated DDL matches Pydantic constraints
   - Test all functions compile successfully
   - Validate foreign key relationships
   - Compare with existing schema for breaking changes

8. **Transaction-Based Deployment**
   ```python
   with conn.transaction():
       for statement in statements:
           cur.execute(statement)
   # All succeed or all rollback
   ```
   - **Benefits**: Atomic deployment, clean rollback on failure

9. **Comprehensive Error Handling**
   - Detailed error messages for failed statements
   - Statement-level retry logic
   - Rollback and recovery procedures
   - **Impact**: Robust deployment process

### 📋 Implementation Checklist

- [ ] Refactor schema_sql_generator.py to use psycopg.sql
- [ ] Fix stage_results parameter naming
- [ ] Add BIGINT casting to function templates
- [ ] Implement constraint extraction from Field definitions
- [ ] Handle Optional types correctly
- [ ] Add transaction wrapper for deployment
- [ ] Create validation test suite
- [ ] Document deployment procedures
- [ ] Add schema comparison tool
- [ ] Implement idempotent deployment

### 🎯 Success Criteria

- ✅ No parsing errors during deployment
- ✅ All functions execute without type mismatches
- ✅ Constraints match Pydantic validation rules
- ✅ Deployment is atomic and recoverable
- ✅ Generated schema passes all validation tests

## Known Issues (Current State)

1. **DO Block Parsing**: Shows errors even when ENUMs created successfully
2. **Parameter Mismatch**: `stage_result` vs `stage_results` causes failures
3. **Type Casting**: Integer literals need explicit BIGINT casting
4. **Error Recovery**: Deployment continues despite statement failures
5. **Constraint Gap**: Pydantic Field constraints not translated to SQL

## Structural Advice Applied (from reference/fromclaude.md)

### Key Architectural Improvements

1. **SQL Composition Safety**
   - Use psycopg.sql module instead of string formatting
   - Proper identifier escaping and injection prevention
   - Better multi-line statement handling

2. **Type Mapping Rigor**
   - Respect max_length for VARCHAR fields
   - Handle Optional correctly (NULL vs NOT NULL)
   - Map complex types (Dict → JSONB)

3. **Constraint Mapping**
   - Extract Field validation rules
   - Generate corresponding CHECK constraints
   - Maintain validation parity between Python and SQL

4. **Model Introspection**
   - Systematic field analysis
   - Extract defaults, constraints, relationships
   - Generate complete DDL with all metadata

## Next Steps

1. **Immediate**: Fix critical issues (DO blocks, parameters, BIGINT)
2. **Short-term**: Implement psycopg.sql and constraint extraction
3. **Medium-term**: Add validation layer and transaction support
4. **Long-term**: Plan Phase 2 based on hardened Phase 1
5. **Future**: Consider function generation from Python signatures