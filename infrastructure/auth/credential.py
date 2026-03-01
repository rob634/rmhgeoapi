# ============================================================================
# SHARED AZURE CREDENTIAL SINGLETON
# ============================================================================
# STATUS: Infrastructure - Canonical credential provider
# PURPOSE: Cached DefaultAzureCredential singleton, safe to import at boot time
# CREATED: 28 FEB 2026
# DEPENDENCIES: azure.identity (no infrastructure dependencies)
# ============================================================================
"""
Shared Azure credential singleton.

Safe to import at boot time — depends only on azure.identity,
not on config or other infrastructure modules. Establishes the
canonical credential provider for modules that need a
DefaultAzureCredential outside repository context (e.g., telemetry
setup that runs before infrastructure is initialized).
"""

from azure.identity import DefaultAzureCredential

_credential = None


def get_azure_credential() -> DefaultAzureCredential:
    """Get cached DefaultAzureCredential singleton."""
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


__all__ = ["get_azure_credential"]
