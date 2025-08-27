# ⚠️ DANGEROUS: STAC Table Clear Method

## Overview
A dangerous method has been added to the DatabaseMetadataService for testing purposes: `clear_stac_tables`

**⚠️ WARNING: This method PERMANENTLY DELETES ALL STAC catalog data. Use with EXTREME CAUTION.**

## Safety Features
- **Required Confirmation**: Must provide exact confirmation string `"YES_DELETE_ALL_STAC_DATA"`  
- **Pre-deletion Counts**: Reports how many collections and items will be deleted
- **Sequence Reset**: Resets auto-increment sequences to start from 1
- **Post-deletion Verification**: Confirms tables are empty
- **Comprehensive Logging**: All operations are logged with warnings

## Usage

### API Endpoint
```bash
POST /api/jobs/clear_stac_tables
```

### Safe Test (Will Fail)
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/clear_stac_tables" \
  -H "Content-Type: application/json" \
  -d '{"system": true}'
```

**Result**: Job will fail with safety check error message.

### Dangerous Clear (Will Delete Everything)
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/clear_stac_tables" \
  -H "Content-Type: application/json" \
  -d '{"system": true, "confirm": "YES_DELETE_ALL_STAC_DATA"}'
```

**Result**: **ALL STAC DATA WILL BE PERMANENTLY DELETED**

## Response Format

### Success Response
```json
{
  "status": "completed",
  "operation": "clear_stac_tables", 
  "timestamp": "2025-08-27T17:15:00.000Z",
  "collections_deleted": 5,
  "items_deleted": 1250,
  "collections_remaining": 0,
  "items_remaining": 0,
  "sequences_reset": true,
  "warning": "⚠️ ALL STAC DATA HAS BEEN PERMANENTLY DELETED",
  "message": "Successfully deleted 5 collections and 1250 items"
}
```

### Safety Check Failure
```json
{
  "status": "failed",
  "error": "ValueError: ⚠️ SAFETY CHECK FAILED: This method will DELETE ALL STAC DATA. To confirm, set confirm='YES_DELETE_ALL_STAC_DATA'. This action is IRREVERSIBLE and should only be used for testing."
}
```

## What Gets Deleted
1. **ALL items** from `geo.items` table
2. **ALL collections** from `geo.collections` table  
3. **Auto-increment sequences** are reset to 1
4. **Foreign key relationships** are properly handled (items deleted first)

## Production Considerations
- **Comment out in production**: Consider removing or commenting out this method for production deployments
- **Database backups**: Always have recent backups before using
- **Access control**: Restrict access to this endpoint in production environments
- **Audit logging**: All clear operations are logged with warnings

## Implementation Details
- Located in: `database_metadata_service.py:1175`
- Service routing: `services.py:450` 
- Requires confirmation string: `"YES_DELETE_ALL_STAC_DATA"`
- Handles foreign key constraints properly
- Provides comprehensive error handling
- Logs all operations with appropriate warning levels

## When to Use
- **Testing scenarios**: Clearing test data between test runs
- **Development reset**: Resetting development databases  
- **Migration testing**: Testing fresh STAC catalog setup

## When NOT to Use  
- **Production environments** (unless absolutely necessary with backups)
- **Shared development** without team coordination
- **Any scenario** where data recovery is important

---

**Remember: This method is IRREVERSIBLE. Deleted STAC data cannot be recovered without database backups.**