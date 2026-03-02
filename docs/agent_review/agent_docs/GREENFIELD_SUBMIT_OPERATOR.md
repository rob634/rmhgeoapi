# Agent O — Operator Assessment: Dashboard Submit Panel

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Input**: Tier 1 spec + Infrastructure Profile

---

## INFRASTRUCTURE FIT

**Overall fit: Moderate — workable but with friction points the spec does not acknowledge.**

**Cold start is the elephant in the room.** Infrastructure profile states 5-15 second cold starts. Spec requires container list in under 1 second and blob list in under 3 seconds. These NFRs are physically impossible on cold start. First operator after idle hits 5-15 second delay before any fragment begins processing.

**HTMX CDN dependency is inherited single point of failure.** HTMX loaded from unpkg.com. If CDN is down, entire submit form is inert HTML. Existing `s.onload` callback fix partially addresses async loading, but CDN outage renders submit form non-functional with no degraded mode.

**Action proxy double-hop.** Submit form posts to `/api/dashboard?action=submit` which makes internal HTTP call to `/api/platform/submit`. Dashboard function instance held alive for full downstream round-trip. Slow downstream API degrades dashboard responsiveness.

**Unused infrastructure capabilities:**
- Application Insights dependency tracking would automatically capture call_api round-trips
- Diagnostic logs for deployment verification of new fragment routes

---

## DEPLOYMENT REQUIREMENTS

**Configuration changes: Minimal.** Code-only change — no new env vars, no database migrations, no DNS, no certificates.

**Dependencies:**
1. `/api/storage/containers` and `/api/storage/{container}/blobs` must be deployed and functional (spec says they exist — must verify post-deployment)
2. `po_*` restructuring in `__init__.py` is shared infrastructure — bug here breaks all submit/validate flows

**Deployment command:** `./deploy.sh orchestrator` or `func azure functionapp publish rmhazuregeoapi --python --build remote`

**Rollback:** Deploy previous commit. No deployment slots on consumption plan. Takes 3-5 min publish + 45s restart + health check.

**Zero-downtime: No.** Consumption plan has no deployment slots. Brief restart window during publish. Acceptable for internal tool.

---

## FAILURE MODES

### FM-1: Cold Start Timeout on Fragment Request
- **Trigger:** Dashboard idle 20+ min, operator opens submit tab
- **Detection:** App Insights shows 5-15s request duration. Operator sees hanging spinner.
- **Blast radius:** Single operator. No data corruption.
- **Recovery:** Refresh page. Second request hits warm instance.
- **Mitigation:** HTMX hx-indicator with "Loading..." message.

### FM-2: Blob Storage API Timeout on Large Container
- **Trigger:** Container with hundreds of blobs. Storage latency or throttling.
- **Detection:** App Insights dependency tracking. Dashboard shows error block.
- **Blast radius:** Single operator. Rest of dashboard works.
- **Recovery:** Retry button (error_block). Use prefix/suffix filters to reduce results.

### FM-3: Action Proxy `po_*` Restructuring Bug Breaks Submit
- **Trigger:** Restructuring logic incorrect — wrong field names, conflicts with existing submissions.
- **Detection:** Submit returns error card. App Insights shows 400/500 on /api/platform/submit.
- **Blast radius:** All dashboard submit operations broken. Possibly cURL submissions if they share the path.
- **Recovery:** Rollback deployment. Fix logic. Redeploy.
- **This is the highest-risk change** — modifies shared infrastructure.

### FM-4: CDN Outage Renders Form Inert
- **Trigger:** unpkg.com unreachable.
- **Detection:** No automated detection. Operator notices form doesn't respond.
- **Blast radius:** Entire dashboard non-functional, not just submit.
- **Recovery:** Wait for CDN recovery. Or vendor HTMX locally. Operators use cURL.
- **Note:** Inherited risk, not introduced by this spec.

### FM-5: Function App Memory Pressure
- **Trigger:** Rapid container switching, multiple concurrent blob list requests.
- **Detection:** App Insights memory metrics. Possible instance restart.
- **Blast radius:** Single instance. All concurrent dashboard requests fail.
- **Recovery:** Automatic restart. Operator refreshes.
- **Likelihood:** Low for single-operator internal tool.

### FM-6: Stale Container/Blob List
- **Trigger:** Files uploaded to storage, submit form opened immediately.
- **Detection:** Operator doesn't see recently uploaded file.
- **Blast radius:** Operator confusion. No data corruption.
- **Recovery:** Re-select container to refresh. Azure Blob is strongly consistent.

---

## OBSERVABILITY

### What Must Be Logged

1. **Every `call_api` invocation** — target path, response status, response time
2. **Action proxy restructuring** — before/after field names (not values) for debugging
3. **Fragment dispatch hits** — which fragment, render time (API latency vs HTML generation)
4. **Submit/validate results** — response status, request_id, job_id on success

### Health Metrics

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Fragment response time (P95) | < 2s | 2-5s | > 5s |
| Submit action response time (P95) | < 5s | 5-10s | > 10s |
| Fragment error rate | 0% | > 5% | > 20% |
| Submit/validate error rate | 0% | > 10% | > 25% |

### Alerts

- Sustained `call_api` failures > 3 in 5 minutes
- Any action proxy 500 (unhandled exception = code bug)

### 3am Diagnosis

Partially achievable via App Insights `requests`, `dependencies`, `exceptions` tables. **Gap:** No structured logging with correlation IDs to trace operator request through proxy to downstream API.

---

## SCALING BEHAVIOR

**This subsystem does not need to scale.** Single-operator internal tool on consumption plan.

**First bottleneck:** Action proxy double-hop — each submit holds function instance for downstream API duration.

**Second bottleneck:** Blob list for containers with 500+ blobs — limit param caps response, but prefix filtering needed.

**Scaling is automatic** (consumption plan) but irrelevant for this use case.

---

## OPERATIONAL HANDOFF

### What a New Operator Must Know

1. Submit panel is the primary write interface — if broken, fall back to cURL
2. Action proxy in `__init__.py` is shared infrastructure — changes affect all dashboard actions
3. Cold starts affect submit disproportionately (chained fragment requests)
4. File browser only shows bronze zone (source data, not processed)
5. No authentication on dashboard

### Documentation Required

1. Fragment route reference (fragment names -> methods -> API endpoints)
2. Action proxy field mapping (po_* -> processing_options)
3. Rollback procedure (deploy previous commit)
4. Known limitations (cold start, 500-blob limit, no multi-file, no zarr browser)

### Runbooks Needed

1. **"Submit form shows error / is blank"** — check health, storage API, App Insights, CDN
2. **"Submit succeeds but job never starts"** — downstream of submit panel, check job status, Service Bus, Docker worker
3. **"File not visible in browser"** — check zone (bronze only), container, prefix filter, 500 limit

---

**Summary:** Moderate-risk addition. Primary risks: (1) action proxy modification in shared code, (2) cold start latency violating NFRs, (3) inherited CDN dependency. None are blockers. NFR latency targets should acknowledge cold start reality. Action proxy change needs careful review.
