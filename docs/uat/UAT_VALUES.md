# UAT Deployment - Reference Values

**Created**: 20 JAN 2026
**Purpose**: Actual values for placeholders in UAT_DEPLOYMENT_PLAN.md and UAT_ESERVICE_REQUESTS.md

---

## Project Information

| Placeholder | Actual Value |
|-------------|--------------|
| Project Name | Geospatial Data Hub (DDHGeo/Chimera) |
| Project Tag | DDHGeo |

---

## Prior QA eService Tickets

| Ticket | Description | Status |
|--------|-------------|--------|
| RITM00009444796 | PostgreSQL setup - MI, extensions, pgstac roles | COMPLETE |
| RITM00009450145 | PostgreSQL reader identity for external database | COMPLETE |

---

## JFROG Artifactory

| Placeholder | Actual Value |
|-------------|--------------|
| `<JFROG_REGISTRY>` | `artifactory.worldbank.org/itsdt-docker-virtual` |

### Full Image References

| Image | Full Path |
|-------|-----------|
| Base GDAL Image | `artifactory.worldbank.org/itsdt-docker-virtual/ubuntu-full:3.10.1` |
| Docker Worker | `artifactory.worldbank.org/itsdt-docker-virtual/geoetl-docker-worker:uat` |
| Service Layer | `artifactory.worldbank.org/itsdt-docker-virtual/geoetl-servicelayer:uat` |

---

## QA Environment Identity Names (for reference)

These are the actual QA identity names from the prior deployment tickets:

| QA Identity | Purpose |
|-------------|---------|
| `migeoeextdbadminqa` | External DB admin (QA) |
| `migeoeextdbreaderqa` | External DB reader (QA) |
| `migeoetldbadminqa` | Internal/ETL DB admin (QA) |
| `migeoetldbreaderqa` | Internal/ETL DB reader (QA) |

---

## QA Environment Resources (for reference)

| Resource Type | QA Name |
|---------------|---------|
| External PostgreSQL Server | `itses-gddatahub-ext-pgsqlsvr-qa` |
| External Database | `geoapp` |
| Resource Group | `itses-gddatahub-qa-rg` |

---

## Terminology Mapping

| Generic Term (in docs) | Actual Term |
|------------------------|-------------|
| "external params" | DDH params |
| "No internal info" | No DDH info |
| "Geospatial ETL Platform" | Geospatial Data Hub (DDHGeo/Chimera) |

---

## Notes

- The UAT deployment plan and eService request templates use generic placeholders
- Replace `<JFROG_REGISTRY>` with the actual artifactory URL when submitting requests
- UAT identity names follow pattern: `mi-geoetl-uat-{zone}-db-{role}`
- QA identity names followed pattern: `migeo{zone}db{role}qa`

---

**Last Updated**: 20 JAN 2026
