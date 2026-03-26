# ============================================================================
# RBAC MODULE — Role-Based Access Control
# ============================================================================
# STATUS: Infrastructure — identity extraction + role gate decorator
# PURPOSE: Read Easy Auth headers, gate endpoints by role
# CREATED: 26 MAR 2026
# EXPORTS: CallerIdentity, get_caller_identity, require_role
# DEPENDENCIES: azure.functions (for HttpResponse in decorator)
# ============================================================================
"""
RBAC Module for Azure Easy Auth.

Extracts caller identity from Easy Auth headers (injected at platform level)
and provides a @require_role() decorator for gating endpoints.

Toggle: AUTH_GATES_ENABLED env var (default: false).
When false, @require_role is a complete no-op — zero overhead.

Usage:
    from infrastructure.auth.rbac import get_caller_identity, require_role

    # Extract identity (always works — returns anonymous if no headers)
    identity = get_caller_identity(req)
    logger.info(f"Request from: {identity.name or 'anonymous'}")

    # Gate an endpoint (only enforced when AUTH_GATES_ENABLED=true)
    @require_role('GeoAdmin')
    def handle_rebuild(req):
        ...

    # Multiple roles — caller needs ANY one
    @require_role('GeoAdmin', 'DataManager')
    def handle_approve(req):
        ...
"""

import base64
import functools
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import azure.functions as func

logger = logging.getLogger(__name__)


@dataclass
class CallerIdentity:
    """Identity extracted from Easy Auth headers."""

    name: Optional[str] = None
    principal_id: Optional[str] = None
    identity_provider: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    email: Optional[str] = None

    @property
    def is_anonymous(self) -> bool:
        return self.principal_id is None


def get_caller_identity(req) -> CallerIdentity:
    """
    Extract caller identity from Easy Auth headers.

    Easy Auth injects these headers after token validation:
        X-MS-CLIENT-PRINCIPAL-NAME — display name
        X-MS-CLIENT-PRINCIPAL-ID — object ID (GUID)
        X-MS-CLIENT-PRINCIPAL-IDP — identity provider ("aad")
        X-MS-CLIENT-PRINCIPAL — base64 JSON blob with all claims

    Returns anonymous identity if headers are absent (no Easy Auth).
    """
    headers = req.headers

    name = headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
    principal_id = headers.get('X-MS-CLIENT-PRINCIPAL-ID')
    idp = headers.get('X-MS-CLIENT-PRINCIPAL-IDP')

    if not principal_id:
        return CallerIdentity()

    # Parse roles from the base64 principal blob
    roles = []
    email = None
    principal_blob = headers.get('X-MS-CLIENT-PRINCIPAL', '')
    if principal_blob:
        try:
            decoded = json.loads(base64.b64decode(principal_blob))
            claims = decoded.get('claims', [])
            for claim in claims:
                if claim.get('typ') == 'roles':
                    roles.append(claim['val'])
                elif claim.get('typ') in ('preferred_username', 'email'):
                    email = claim['val']
        except Exception as e:
            logger.debug(f"Could not parse X-MS-CLIENT-PRINCIPAL blob: {e}")

    return CallerIdentity(
        name=name,
        principal_id=principal_id,
        identity_provider=idp,
        roles=roles,
        email=email,
    )


def _get_auth_config():
    """Get auth config — separated for testability."""
    from config import get_config
    return get_config().auth


def require_role(*roles: str):
    """
    Decorator to gate an endpoint by one or more roles (caller needs ANY one).

    When AUTH_GATES_ENABLED=false (default): complete no-op, zero overhead.
    When AUTH_GATES_ENABLED=true:
        - Anonymous caller -> 401
        - Caller without any required role -> 403
        - Caller with at least one required role -> passes through

    Usage:
        @require_role('GeoAdmin')
        def handle_rebuild(req):
            ...

        @require_role('GeoAdmin', 'DataManager')
        def handle_approve(req):
            ...

    The decorated function must accept an HttpRequest as its first argument.
    """
    required_roles = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(req, *args, **kwargs):
            config = _get_auth_config()

            if not config.gates_enabled:
                return fn(req, *args, **kwargs)

            identity = get_caller_identity(req)

            if identity.is_anonymous:
                logger.warning(
                    f"[RBAC] 401 — anonymous request to {fn.__name__} "
                    f"(requires: {required_roles})"
                )
                return func.HttpResponse(
                    json.dumps({
                        'error': 'Authentication required',
                        'detail': 'This endpoint requires authentication. '
                                  'Please sign in or provide a valid Bearer token.',
                    }),
                    status_code=401,
                    mimetype='application/json',
                )

            caller_roles = set(identity.roles)
            if not caller_roles & required_roles:
                # Log details server-side but do NOT expose role names to client
                logger.warning(
                    f"[RBAC] 403 — {identity.name} ({identity.principal_id}) "
                    f"has roles {identity.roles}, needs one of {required_roles} "
                    f"for {fn.__name__}"
                )
                return func.HttpResponse(
                    json.dumps({
                        'error': 'Insufficient permissions',
                        'detail': 'You do not have permission to access this endpoint.',
                    }),
                    status_code=403,
                    mimetype='application/json',
                )

            logger.info(
                f"[RBAC] Authorized: {identity.name} -> {fn.__name__}"
            )
            return fn(req, *args, **kwargs)
        return wrapper
    return decorator
