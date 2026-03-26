# ============================================================================
# AUTH/RBAC CONFIGURATION
# ============================================================================
# STATUS: Configuration - Role-Based Access Control settings
# PURPOSE: Toggle auth gates for Easy Auth environments
# CREATED: 26 MAR 2026
# ============================================================================
"""
Auth/RBAC Configuration.

Controls whether role-based access gates are enforced.
When AUTH_GATES_ENABLED=false (default), all @require_role decorators are no-ops.

Environment Variables:
----------------------
AUTH_GATES_ENABLED: Master switch for role enforcement (default: false)

Usage:
------
```python
from config import get_config

config = get_config()
if config.auth.gates_enabled:
    # enforce role checks
```
"""

import os
from pydantic import BaseModel, Field

from .defaults import AuthDefaults, parse_bool


class AuthConfig(BaseModel):
    """
    Auth/RBAC configuration.

    Configuration Fields:
    ---------------------
    gates_enabled: Master switch for @require_role enforcement
        - False: All @require_role decorators are no-ops (default)
        - True: Enforce role checks from Easy Auth headers
    """

    gates_enabled: bool = Field(
        default=AuthDefaults.AUTH_GATES_ENABLED,
        description="When True, @require_role decorators enforce role checks"
    )

    @classmethod
    def from_environment(cls) -> 'AuthConfig':
        """Create AuthConfig from environment variables."""
        return cls(
            gates_enabled=parse_bool(
                os.environ.get('AUTH_GATES_ENABLED', str(AuthDefaults.AUTH_GATES_ENABLED))
            ),
        )

    def debug_dict(self) -> dict:
        """Return sanitized dict for debug output."""
        return {
            'gates_enabled': self.gates_enabled,
        }
