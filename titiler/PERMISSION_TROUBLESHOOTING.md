# PostgreSQL Permission Troubleshooting Guide

**Date**: 28 OCT 2025
**Issue**: TiTiler can't access pgstac schema, but DBeaver can see everything

## Important Discovery 🔍

**You said**: "I can see everything in DBeaver with {db_superuser} when on my home network"

This is very interesting! It means one of two things:

### Possibility 1: DBeaver Uses Different Connection
DBeaver might be connecting with:
- Different user (check connection properties)
- Different database
- Different schema search path
- Saved password for different user

### Possibility 2: Network-Based Permissions
PostgreSQL might have different permissions based on connection source:
- Home network IP has broader access
- Azure Web App IP has restricted access
- Check `pg_hba.conf` equivalent in Azure

### Possibility 3: {db_superuser} Actually Has Permissions
If {db_superuser} can see pgstac in DBeaver, permissions might be fine. The issue could be:
- TiTiler's search_path doesn't include pgstac
- TiTiler's connection string is slightly different
- SSL mode difference causing schema visibility issues

## Diagnostic Steps

### Step 1: Check DBeaver Connection Properties

In DBeaver when you're home:
1. Right-click your connection → "Edit Connection"
2. Check these settings:
   - **User**: Is it really "{db_superuser}"?
   - **Database**: Is it "postgres"?
   - **Properties tab**: Any special parameters?
   - **SSH tunnel**: Are you using SSH tunneling?

### Step 2: Run Permission Check Script

When you're home and connected with DBeaver:

```sql
-- Run this in DBeaver to see actual permissions
\i /path/to/check_permissions.sql
```

Or copy/paste the contents of `check_permissions.sql` directly into DBeaver's SQL editor.

**Key sections to look at**:
- Section 3: "Does {db_superuser} have USAGE on pgstac schema?"
- Section 6: "Is {db_superuser} member of pgstac_read role?"
- Section 12: "Test calling pgstac.all_collections() function"

### Step 3: Compare Connection Details

Run this in DBeaver:
```sql
-- See exactly how you're connected
SELECT
    current_user AS user,
    current_database() AS database,
    inet_client_addr() AS client_ip,
    inet_server_addr() AS server_ip,
    application_name,
    pg_backend_pid() AS connection_pid;

-- See current search path
SHOW search_path;

-- List all schemas visible to current connection
SELECT schema_name
FROM information_schema.schemata
ORDER BY schema_name;
```

Compare this to TiTiler's environment:
```bash
POSTGRES_USER={db_superuser}
POSTGRES_DBNAME=postgres
POSTGRES_SCHEMA=pgstac
```

## Common Scenarios

### Scenario A: DBeaver Uses Different User
**Symptom**: DBeaver shows different user in query results
**Solution**: Get that user's credentials and use in TiTiler

```bash
# Update TiTiler to use correct user
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings \
    POSTGRES_USER=actual_user \
    POSTGRES_PASS=actual_password
```

### Scenario B: {db_superuser} Has Permissions, But Schema Not In Search Path
**Symptom**: You can query `pgstac.collections` but not just `collections`
**Solution**: Add pgstac to search path

```sql
-- Run as admin or {db_superuser} (if allowed)
ALTER USER {db_superuser} SET search_path TO public, pgstac;
```

Then restart TiTiler:
```bash
az webapp restart --resource-group rmhazure_rg --name rmhtitiler
```

### Scenario C: Permissions Are Actually Missing
**Symptom**: check_permissions.sql shows false for key permissions
**Solution**: Grant permissions using fix_permissions.sql

Connect as admin user:
```bash
# Connect as admin
psql -h rmhpgflex.postgres.database.azure.com -U <admin_user> -d postgres

# Run the fix script
\i fix_permissions.sql
```

### Scenario D: Azure Firewall + pg_hba.conf Rules
**Symptom**: Works from home, not from Azure
**Solution**: Check Azure PostgreSQL firewall rules

We already verified this - Azure services are allowed:
```bash
AllowAllAzureServicesAndResourcesWithinAzureIps (0.0.0.0)
```

But if this rule got removed, re-add it:
```bash
az postgres flexible-server firewall-rule create \
  --resource-group rmhazure_rg \
  --name rmhpgflex \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

## Testing Matrix

| Test | Expected Result | What It Means |
|------|----------------|---------------|
| DBeaver: `SELECT * FROM pgstac.collections` | Works | Schema exists and is accessible |
| DBeaver: `SELECT current_user` | Returns '{db_superuser}' | Confirms you're using {db_superuser} |
| DBeaver: `SELECT * FROM pgstac.all_collections()` | Works | {db_superuser} can execute pgstac functions |
| DBeaver: `SHOW search_path` | Contains 'pgstac' | Schema in default path |
| SQL: `has_schema_privilege('{db_superuser}', 'pgstac', 'USAGE')` | Returns true | {db_superuser} has schema access |
| SQL: `pg_has_role('{db_superuser}', 'pgstac_read', 'MEMBER')` | Returns true | {db_superuser} in pgstac_read role |

## What to Send Me

When you're home and can run the diagnostic script, send me:

1. **Output from check_permissions.sql**, especially:
   - Section 3 (USAGE privilege)
   - Section 6 (pgstac_read membership)
   - Section 10 (search_path)
   - Section 12 (all_collections() call)

2. **DBeaver connection properties**:
   - Screenshot or text of connection settings
   - User shown in connection properties
   - Any special connection parameters

3. **This simple query result**:
```sql
SELECT
    current_user,
    current_database(),
    has_schema_privilege('{db_superuser}', 'pgstac', 'USAGE') AS can_use_pgstac,
    pg_has_role('{db_superuser}', 'pgstac_read', 'MEMBER') AS is_pgstac_reader;
```

## Quick Fix Commands (When Home)

### If {db_superuser} lacks permissions:
```sql
-- Connect as admin
GRANT pgstac_read TO {db_superuser};
```

### If search_path is the issue:
```sql
-- Connect as admin or {db_superuser}
ALTER USER {db_superuser} SET search_path TO public, pgstac;
```

### Test immediately:
```sql
-- Should work after fix
SELECT * FROM pgstac.all_collections();
```

Then test TiTiler:
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections"
```

## Files to Use When Home

1. **check_permissions.sql** - Run this first to diagnose
2. **fix_permissions.sql** - Run this (as admin) if permissions are missing
3. **This file** - Reference for troubleshooting

## Most Likely Scenario

Based on "I can see everything in DBeaver":

**Hypothesis**: {db_superuser} probably DOES have permissions, but either:
- TiTiler's connection has a different search_path
- TiTiler is missing `POSTGRES_SCHEMA=pgstac` (wait, we set this!)
- There's a subtle difference in how TiTiler's psycopg library interprets the schema

**Quick test when home**:
```sql
-- See if this is a search_path issue
ALTER USER {db_superuser} SET search_path TO public, pgstac;
```

Then restart TiTiler and test again!

## Summary

🏠 **When you get home**:
1. Connect to PostgreSQL with DBeaver
2. Run `check_permissions.sql`
3. Note the results from sections 3, 6, 10, and 12
4. If section 12 works, it's likely a search_path issue
5. Run `ALTER USER {db_superuser} SET search_path TO public, pgstac;`
6. Restart TiTiler
7. Test!

The fact that DBeaver works is actually GOOD NEWS - it means the infrastructure is fine, just a configuration tweak needed! 🎉