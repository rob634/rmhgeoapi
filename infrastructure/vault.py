# ============================================================================
# CLAUDE CONTEXT - VAULT REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Azure Key Vault repository (disabled pending RBAC)
# PURPOSE: Azure Key Vault repository for secure credential management (currently disabled pending RBAC setup)
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: VaultRepository, VaultRepositoryFactory, VaultAccessError
# INTERFACES: None - standalone repository for Key Vault operations
# PYDANTIC_MODELS: None - uses dict for vault information
# DEPENDENCIES: azure.keyvault.secrets, azure.identity, azure.core, util_logger, typing, datetime, config
# SOURCE: Azure Key Vault via DefaultAzureCredential, environment variables for vault name
# SCOPE: Global credential management for database passwords and application secrets
# VALIDATION: Secret name validation, credential authentication, vault access permissions
# PATTERNS: Repository pattern, Factory pattern, Caching pattern (with TTL), Singleton (via factory)
# ENTRY_POINTS: VaultRepositoryFactory.create_with_config() - Currently disabled
# INDEX: VaultRepository:46, get_secret:83, get_database_password:128, VaultRepositoryFactory:223
# ============================================================================

"""
Azure Key Vault Repository - Secure Credential Management

Provides secure access to sensitive configuration values like database passwords
following the same repository pattern as other data access layers.

Security Features:
- DefaultAzureCredential for managed identity authentication
- Credential caching for performance 
- Explicit error handling for vault access failures
- Type-safe credential retrieval with validation

Integration with Database Repository:
- PostgresAdapter will use VaultRepository to retrieve POSTGIS_PASSWORD
- Eliminates hardcoded credentials in connection strings
- Supports Azure Functions managed identity authentication
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError

from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "VaultRepository")


class VaultAccessError(Exception):
    """Custom exception for vault access failures"""
    pass


class VaultRepository:
    """
    Azure Key Vault repository for secure credential management.
    
    Follows the same error handling and logging patterns as other repositories
    in the system for consistency.
    
    Usage:
        vault_repo = VaultRepository()
        db_password = vault_repo.get_secret("postgis-password")
    """
    
    def __init__(self, vault_name: Optional[str] = None):
        """
        Initialize vault repository with Azure Key Vault client.
        
        Args:
            vault_name: Key Vault name (defaults to KEY_VAULT env var or rmhazurevault)
        """
        from config import get_config
        config = get_config()

        self.vault_name = vault_name or config.key_vault_name
        self.vault_url = f"https://{self.vault_name}.vault.azure.net/"
        
        # Initialize Azure credentials
        try:
            self.credential = DefaultAzureCredential()
            self.client = SecretClient(vault_url=self.vault_url, credential=self.credential)
            logger.info(f"🔐 VaultRepository initialized for vault: {self.vault_name}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize VaultRepository: {e}")
            raise VaultAccessError(f"Vault client initialization failed: {e}")
        
        # Simple in-memory cache for secrets (Azure Functions are stateless)
        self._secret_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_minutes = 15  # Cache secrets for 15 minutes
    
    def get_secret(self, secret_name: str, use_cache: bool = True) -> str:
        """
        Retrieve secret value from Azure Key Vault.
        
        Args:
            secret_name: Name of the secret in Key Vault
            use_cache: Whether to use cached value if available
            
        Returns:
            Secret value as string
            
        Raises:
            VaultAccessError: If secret cannot be retrieved
        """
        logger.debug(f"🔐 Retrieving secret: {secret_name}")
        
        # Check cache first (if enabled)
        if use_cache and self._is_secret_cached(secret_name):
            logger.debug(f"🔐 Using cached secret: {secret_name}")
            return self._secret_cache[secret_name]['value']
        
        try:
            # Retrieve secret from Azure Key Vault
            secret = self.client.get_secret(secret_name)
            secret_value = secret.value
            
            if not secret_value:
                raise VaultAccessError(f"Secret '{secret_name}' is empty or null")
            
            # Cache the secret value
            if use_cache:
                self._cache_secret(secret_name, secret_value)
            
            logger.info(f"✅ Successfully retrieved secret: {secret_name}")
            return secret_value
            
        except AzureError as e:
            error_msg = f"Failed to retrieve secret '{secret_name}' from vault '{self.vault_name}': {e}"
            logger.error(f"❌ {error_msg}")
            raise VaultAccessError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error retrieving secret '{secret_name}': {e}"
            logger.error(f"❌ {error_msg}")
            raise VaultAccessError(error_msg)
    
    def get_database_password(self, database_type: str = 'postgis') -> str:
        """
        Retrieve database password for the specified database type.
        
        Convenience method for common database credential patterns.
        
        Args:
            database_type: Type of database ('postgis', 'cosmos', etc.)
            
        Returns:
            Database password
            
        Raises:
            VaultAccessError: If password cannot be retrieved
        """
        secret_name = f"{database_type}-password"
        logger.debug(f"🔐 Retrieving database password for: {database_type}")
        
        try:
            password = self.get_secret(secret_name)
            logger.info(f"✅ Successfully retrieved {database_type} password")
            return password
        except VaultAccessError:
            # Try alternative naming patterns
            alternative_names = [
                f"{database_type.upper()}-PASSWORD",
                f"{database_type}_password", 
                f"{database_type.upper()}_PASSWORD"
            ]
            
            for alt_name in alternative_names:
                try:
                    logger.debug(f"🔐 Trying alternative secret name: {alt_name}")
                    password = self.get_secret(alt_name)
                    logger.info(f"✅ Successfully retrieved {database_type} password using: {alt_name}")
                    return password
                except VaultAccessError:
                    continue
            
            # If all attempts failed, raise the original error
            raise VaultAccessError(f"Could not find database password for {database_type}. "
                                 f"Tried: {secret_name}, {', '.join(alternative_names)}")
    
    def _is_secret_cached(self, secret_name: str) -> bool:
        """Check if secret is cached and not expired."""
        if secret_name not in self._secret_cache:
            return False
        
        cached_time = self._secret_cache[secret_name]['cached_at']
        expiry_time = cached_time + timedelta(minutes=self._cache_ttl_minutes)
        
        if datetime.now(timezone.utc) > expiry_time:
            # Cache expired, remove it
            del self._secret_cache[secret_name]
            return False
        
        return True
    
    def _cache_secret(self, secret_name: str, secret_value: str) -> None:
        """Cache secret value with timestamp."""
        self._secret_cache[secret_name] = {
            'value': secret_value,
            'cached_at': datetime.now(timezone.utc)
        }
        logger.debug(f"🔐 Cached secret: {secret_name}")
    
    def clear_cache(self) -> int:
        """
        Clear all cached secrets.
        
        Returns:
            Number of secrets cleared from cache
        """
        count = len(self._secret_cache)
        self._secret_cache.clear()
        logger.info(f"🔐 Cleared {count} secrets from cache")
        return count
    
    def get_vault_info(self) -> Dict[str, Any]:
        """
        Get vault repository information for debugging.
        
        Returns:
            Dictionary with vault configuration and cache status
        """
        return {
            'vault_name': self.vault_name,
            'vault_url': self.vault_url,
            'cache_ttl_minutes': self._cache_ttl_minutes,
            'cached_secrets_count': len(self._secret_cache),
            'cached_secret_names': list(self._secret_cache.keys()),
            'authentication_type': 'DefaultAzureCredential (Managed Identity)'
        }


class VaultRepositoryFactory:
    """Factory for creating VaultRepository instances with different configurations."""
    
    @staticmethod
    def create_vault_repository(vault_name: Optional[str] = None) -> VaultRepository:
        """
        Create VaultRepository instance.
        
        Args:
            vault_name: Override vault name (defaults to environment/config)
            
        Returns:
            Configured VaultRepository instance
        """
        return VaultRepository(vault_name=vault_name)
    
    @staticmethod
    def create_with_config() -> VaultRepository:
        """
        Create VaultRepository using application configuration.
        
        Returns:
            VaultRepository configured from app settings
        """
        try:
            from config import get_config
            config = get_config()
            
            # Check if config has a key_vault_name field
            vault_name = getattr(config, 'key_vault_name', None)
            if not vault_name:
                # Fallback to config
                from config import get_config
                config = get_config()
                vault_name = config.key_vault_name
            
            return VaultRepository(vault_name=vault_name)
            
        except ImportError:
            logger.warning("⚠️ Config module not available, using default vault configuration")
            return VaultRepository()
        except Exception as e:
            logger.warning(f"⚠️ Failed to load config for vault, using defaults: {e}")
            return VaultRepository()


# Export public interfaces
__all__ = [
    'VaultRepository',
    'VaultRepositoryFactory', 
    'VaultAccessError'
]