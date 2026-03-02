# Routing & ADF Public Data Pipeline — Design Reference

**Created**: 02 MAR 2026
**Status**: APPROVED DESIGN
**Canonical Location**: `/Users/robertharrison/python_builds/rmhtitiler/ROUTING_DESIGN.md`

---

## Summary

This design covers the `geo.b2c_routes` / `geo.b2b_routes` tables and the ADF
`export_to_public` pipeline for moving PUBLIC data from internal to external
security zones.

**The full design document lives in rmhtitiler** because it spans both projects
and the service layer (rmhtitiler) is the primary consumer of the routes table.

## rmhgeoapi Responsibilities

1. **Schema DDL**: Add `geo.b2c_routes` + `geo.b2b_routes` to `core/schema/sql_generator.py`
2. **Route Repository**: Create `infrastructure/route_repository.py`
3. **Approval Integration**: Write routes in `services/asset_approval_service.py`
4. **ADF Trigger**: Pass slug + route data to ADF pipeline parameters
5. **Revocation**: Delete routes and promote next latest

## Implementation Checklist (rmhgeoapi only)

- [ ] Add `geo.b2c_routes` + `geo.b2b_routes` DDL to `core/schema/sql_generator.py`
- [ ] Create `infrastructure/route_repository.py` (upsert, delete, clear_latest, promote_next)
- [ ] Wire route creation into `services/asset_approval_service.py` (approve + revoke)
- [ ] Add `slug` parameter to ADF pipeline trigger
- [ ] Deploy + `action=ensure` to create tables
- [ ] Verify: approve a release → route record appears

## See Also

- **Full design**: `rmhtitiler/ROUTING_DESIGN.md`
- **Approval workflow**: `docs_claude/APPROVAL_WORKFLOW.md`
- **ADF repository**: `infrastructure/data_factory.py`
- **Slug generation**: `config/platform_config.py` → `_slugify_for_stac()`
