# ============================================================================
# CLAUDE CONTEXT - UTILITY
# ============================================================================
# CATEGORY: CROSS-CUTTING UTILITIES
# PURPOSE: Validation and diagnostic utilities used throughout codebase
# EPOCH: Shared by all epochs (utilities)# PURPOSE: Zero-configuration import validation with auto-discovery of application modules
# EXPORTS: ImportValidator, validator (singleton instance)
# INTERFACES: None - utility class for import validation
# PYDANTIC_MODELS: None - uses dict for validation results
# DEPENDENCIES: os, sys, time, traceback, json, glob, importlib, pathlib, typing, datetime
# SOURCE: Filesystem scanning for *.py files, predefined critical modules list, environment variables
# SCOPE: Global application health monitoring with persistent registry tracking
# VALIDATION: Two-tier system (critical external deps + auto-discovered app modules), import testing
# PATTERNS: Singleton pattern, Registry pattern, Auto-discovery pattern, Health Check pattern
# ENTRY_POINTS: validator.ensure_startup_ready(); health = validator.get_health_status()
# INDEX: ImportValidator:59, validate_all_imports:390, ensure_startup_ready:604, get_health_status:644
# ============================================================================

"""
Import Validation System for Azure Geospatial ETL Pipeline.

This module provides fail-first import validation that ensures all critical dependencies
are available before the Azure Function app starts processing requests. It combines
startup validation with ongoing health monitoring through cached validation results.

Key Features:
    - Fail-fast startup validation prevents silent import failures
    - Cached validation results (5-minute TTL) for performance
    - Structured logging with visual indicators for debugging
    - Environment-based activation (auto-detects Azure Functions)
    - Detailed error reporting for missing dependencies
    - Health check integration for ongoing monitoring

Architecture:
    ImportValidator (Singleton) → Cached Results → Structured Logging
                    ↓
    Startup Validation (function_app.py) + Health Monitoring (trigger_health.py)

Usage:
    # Automatic startup validation
    from utils import validator
    validator.ensure_startup_ready()  # Raises ImportError if critical deps missing
    
    # Health check integration  
    health_status = validator.get_health_status()  # Returns detailed status dict

Version: 1.0.0
Last Updated: September 2025
"""

import os
import sys
import time
import traceback
import json
import glob
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Initialize logging first - critical for debugging import issues
from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext


class ImportValidator:
    """
    Auto-Discovery Import Validation System for Azure Functions.
    
    This singleton class provides zero-configuration import validation by automatically 
    discovering application modules through filesystem scanning and maintaining a persistent
    registry of validation status for both critical external dependencies and application code.
    
    ## Two-Tier Validation System:
    
    **1. Critical Modules (External Dependencies):**
        - azure.functions, azure.identity, azure.storage.queue
        - pydantic, psycopg, json, logging, os, sys
        - Predefined list of essential dependencies
        
    **2. Application Modules (Auto-Discovered):**
        - Scans filesystem for Python files using naming patterns
        - service_*.py → "* service implementation"
        - model_*.py → "* Pydantic model definitions"
        - repository_*.py → "* repository layer"
        - trigger_*.py → "* HTTP trigger class"
        - util_*.py → "* utility module"
        - validator_*.py → "* validation utilities"
        - schema_*.py → "* schema definitions"
        - adapter_*.py → "* adapter layer"
    
    ## Registry Structure (import_validation_registry.json):
    
    ```json
    {
      "critical_modules": {
        "azure.functions": {
          "description": "Azure Functions runtime",
          "discovered_date": "2025-09-05T...",
          "last_successful_validation": "2025-09-05T...",
          "auto_discovered": false
        }
      },
      "application_modules": {
        "service_hello_world": {
          "description": "Hello World service implementation",
          "discovered_date": "2025-10-01T...",
          "last_successful_validation": "2025-10-01T...",
          "auto_discovered": true
        }
      },
      "metadata": {
        "created": "2025-09-05T...",
        "last_updated": "2025-09-05T...",
        "version": "1.0"
      }
    }
    ```
    
    ## Key Benefits:
        - **Zero Configuration**: New classes automatically included when following naming conventions
        - **Early Detection**: Import failures caught before runtime in Azure Functions
        - **Health Monitoring**: Real-time status via /api/health endpoint
        - **Development Workflow**: Clean registry shows only essential data (last validation timestamp)
        - **Azure Functions Ready**: Skips file writes in read-only filesystem environments
        
    ## Usage in Development:
        When adding new classes like `service_raster_processor.py` or `trigger_geospatial.py`,
        they are automatically discovered and included in import validation within 6 minutes
        (health check interval). No manual configuration required.
    
    ## Caching & Performance:
        - 5-minute cache TTL prevents repeated filesystem scanning
        - Registry updates only on module discovery or validation status changes
        - Singleton pattern ensures consistent state across Azure Functions runtime
    """
    
    _instance: Optional['ImportValidator'] = None
    _last_validation: Optional[Dict[str, Any]] = None
    _validation_timestamp: Optional[datetime] = None
    _cache_duration = timedelta(minutes=5)  # 5-minute cache for performance
    _registry_file = "import_validation_registry.json"  # Config file for discovered modules
    
    def __new__(cls) -> 'ImportValidator':
        """Ensure singleton pattern for consistent state."""
        if cls._instance is None:
            cls._instance = super(ImportValidator, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize validator with logger and environment detection."""
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.logger = LoggerFactory.create_logger(ComponentType.VALIDATOR, "ImportValidator")
        self.is_azure_functions = self._detect_azure_functions_environment()
        self.force_validation = os.getenv('VALIDATE_IMPORTS', '').lower() == 'true'
        self._initialized = True
        
        # Log initialization
        self.logger.info(f"🔧 ImportValidator initialized - Azure Functions: {self.is_azure_functions}, Force: {self.force_validation}")
    
    def _detect_azure_functions_environment(self) -> bool:
        """
        Detect if running in Azure Functions environment.
        
        Returns:
            bool: True if running in Azure Functions, False otherwise.
        """
        # Azure Functions sets these environment variables
        azure_indicators = [
            'AZURE_FUNCTIONS_ENVIRONMENT',
            'AzureWebJobsStorage',
            'FUNCTIONS_WORKER_RUNTIME',
            'WEBSITE_SITE_NAME'
        ]
        
        detected = any(os.getenv(var) for var in azure_indicators)
        
        if detected:
            self.logger.debug(f"🌩️ Azure Functions environment detected via environment variables")
        else:
            self.logger.debug(f"💻 Local development environment detected")
            
        return detected
    
    def _load_module_registry(self) -> Dict[str, Any]:
        """
        Load the persistent module registry from JSON file.
        
        Returns:
            Dict with module registry data or empty structure if file doesn't exist.
        """
        registry_path = Path(self._registry_file)
        
        if not registry_path.exists():
            self.logger.debug(f"📂 Registry file not found, creating new registry: {self._registry_file}")
            return {
                'metadata': {
                    'created': datetime.now(timezone.utc).isoformat(),
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'version': '1.0'
                },
                'critical_modules': {},
                'application_modules': {}
            }
        
        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)
                self.logger.debug(f"📋 Loaded module registry with {len(registry.get('critical_modules', {}))} critical and {len(registry.get('application_modules', {}))} application modules")
                return registry
                
        except (json.JSONDecodeError, IOError) as e:
            self.logger.warning(f"⚠️ Failed to load registry file, creating new: {e}")
            return {
                'metadata': {
                    'created': datetime.now(timezone.utc).isoformat(),
                    'last_updated': datetime.now(timezone.utc).isoformat(),
                    'version': '1.0',
                    'load_error': str(e)
                },
                'critical_modules': {},
                'application_modules': {}
            }
    
    def _save_module_registry(self, registry: Dict[str, Any]) -> None:
        """
        Save the module registry to JSON file with updated timestamp.
        
        Args:
            registry: Registry data to save.
        """
        # Skip file operations in Azure Functions (read-only filesystem)
        if self.is_azure_functions:
            self.logger.debug(f"⚠️ Skipping registry save in Azure Functions (read-only filesystem)")
            return
            
        try:
            # Update metadata
            registry['metadata']['last_updated'] = datetime.now(timezone.utc).isoformat()
            
            registry_path = Path(self._registry_file)
            with open(registry_path, 'w') as f:
                json.dump(registry, f, indent=2, sort_keys=True)
                
            self.logger.debug(f"💾 Saved module registry to {self._registry_file}")
            
        except IOError as e:
            self.logger.error(f"❌ Failed to save registry file: {e}")
    
    def _discover_application_modules(self) -> List[Tuple[str, str]]:
        """
        Auto-discover application modules by scanning filesystem patterns.
        
        Returns:
            List of (module_name, description) tuples for discovered modules.
        """
        discovered_modules = []
        current_dir = Path.cwd()
        
        self.logger.debug(f"🔍 Auto-discovering modules in: {current_dir}")
        
        # Module discovery patterns with descriptions
        # NOTE: controller_*.py REMOVED (1 OCT 2025) - Epoch 3 controllers deprecated
        discovery_patterns = [
            # ('controller_*.py', 'workflow controller'),  # REMOVED - Epoch 3 deprecated
            ('service_*.py', 'service implementation'),
            ('model_*.py', 'Pydantic model definitions'),
            ('validator_*.py', 'validation utilities'),
            ('adapter_*.py', 'adapter layer'),
            ('repository_*.py', 'repository layer'),
            ('trigger_*.py', 'HTTP trigger class'),
            ('util_*.py', 'utility module'),
            ('schema_*.py', 'schema definitions')
        ]
        
        for pattern, description_suffix in discovery_patterns:
            matching_files = glob.glob(pattern)
            
            for file_path in matching_files:
                # Convert file path to module name (remove .py extension)
                module_name = Path(file_path).stem
                
                # Skip __init__ files - they don't import like regular modules
                if module_name == '__init__':
                    continue
                    
                # Create descriptive name based on module name and pattern
                if module_name.startswith('service_'):
                    description = f"{module_name.replace('service_', '').replace('_', ' ').title()} {description_suffix}"
                elif module_name.startswith('model_'):
                    description = f"{module_name.replace('model_', '').replace('_', ' ').title()} {description_suffix}"
                elif module_name.startswith('trigger_'):
                    description = f"{module_name.replace('trigger_', '').replace('_', ' ').title()} {description_suffix}"
                elif module_name.startswith('util_'):
                    description = f"{module_name.replace('util_', '').replace('_', ' ').title()} {description_suffix}"
                else:
                    description = f"{module_name.replace('_', ' ').title()} {description_suffix}"
                
                discovered_modules.append((module_name, description))
                self.logger.debug(f"🔎 Discovered: {module_name} - {description}")
        
        # Add core modules that don't follow patterns
        core_modules = [
            ('schema_core', 'Core schema definitions and enums'),
            ('config', 'Application configuration management'),
            ('function_app', 'Azure Functions entry point')
        ]
        
        for module_name, description in core_modules:
            file_path = f"{module_name}.py"
            if Path(file_path).exists():
                discovered_modules.append((module_name, description))
                self.logger.debug(f"🔎 Discovered core module: {module_name} - {description}")
        
        self.logger.info(f"🔍 Auto-discovery complete: found {len(discovered_modules)} application modules")
        return discovered_modules
    
    def _update_registry_with_discoveries(self, registry: Dict[str, Any], discovered_modules: List[Tuple[str, str]]) -> Dict[str, Any]:
        """
        Update registry with newly discovered modules and validation results.
        
        Args:
            registry: Current registry data.
            discovered_modules: List of discovered (module_name, description) tuples.
            
        Returns:
            Updated registry data.
        """
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Update application modules section
        for module_name, description in discovered_modules:
            if module_name not in registry['application_modules']:
                # New module discovered
                registry['application_modules'][module_name] = {
                    'description': description,
                    'discovered_date': current_time,
                    'last_successful_validation': None,
                    'auto_discovered': True
                }
                self.logger.info(f"📝 Registered new module: {module_name} - {description}")
            else:
                # Update description if it has changed
                if registry['application_modules'][module_name]['description'] != description:
                    registry['application_modules'][module_name]['description'] = description
                    self.logger.debug(f"📝 Updated description for {module_name}: {description}")
        
        return registry
    
    def _record_validation_results(self, registry: Dict[str, Any], validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record validation results in the registry for historical tracking.
        
        Args:
            registry: Current registry data.
            validation_results: Results from validate_all_imports().
            
        Returns:
            Updated registry with validation history.
        """
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Update critical modules validation history
        for module_name, details in validation_results['critical_imports']['details'].items():
            if module_name not in registry['critical_modules']:
                registry['critical_modules'][module_name] = {
                    'description': details.get('description', 'Critical dependency'),
                    'discovered_date': current_time,
                    'last_successful_validation': None,
                    'auto_discovered': False
                }
            
            # Update last successful validation timestamp
            if details['status'] == 'success':
                registry['critical_modules'][module_name]['last_successful_validation'] = current_time
        
        # Update application modules validation status
        for module_name, details in validation_results['application_modules']['details'].items():
            if module_name in registry['application_modules']:
                # Update last successful validation timestamp
                if details['status'] == 'success':
                    registry['application_modules'][module_name]['last_successful_validation'] = current_time
        
        return registry
    
    def _is_cache_valid(self) -> bool:
        """Check if cached validation results are still valid."""
        if self._last_validation is None or self._validation_timestamp is None:
            return False
            
        age = datetime.now(timezone.utc) - self._validation_timestamp
        return age < self._cache_duration
    
    def validate_all_imports(self, force_recheck: bool = False) -> Dict[str, Any]:
        """
        Perform comprehensive import validation with caching.
        
        Args:
            force_recheck: If True, bypass cache and perform fresh validation.
            
        Returns:
            Dict containing validation results with structure:
            {
                'success': bool,
                'timestamp': str,
                'critical_imports': {'success': bool, 'failed': List[str], 'details': Dict},
                'application_modules': {'success': bool, 'failed': List[str], 'details': Dict},
                'warnings': List[str],
                'environment': Dict[str, Any]
            }
        """
        # Return cached results if valid and not forcing recheck
        if not force_recheck and self._is_cache_valid():
            self.logger.debug(f"📋 Using cached validation results (age: {datetime.now(timezone.utc) - self._validation_timestamp})")
            return self._last_validation
        
        self.logger.info(f"🔍 Starting comprehensive import validation with auto-discovery (force_recheck={force_recheck})")
        
        # Load persistent module registry
        registry = self._load_module_registry()
        
        # Auto-discover application modules
        discovered_modules = self._discover_application_modules()
        
        # Update registry with discovered modules
        registry = self._update_registry_with_discoveries(registry, discovered_modules)
        
        # Initialize validation result structure
        validation_result = {
            'success': True,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'critical_imports': {'success': True, 'failed': [], 'details': {}},
            'application_modules': {'success': True, 'failed': [], 'details': {}},
            'warnings': [],
            'environment': self._get_environment_info(),
            'auto_discovery': {
                'modules_discovered': len(discovered_modules),
                'discovery_patterns_used': 9,  # Number of patterns in _discover_application_modules
                'registry_updated': True
            }
        }
        
        # Validate critical imports (Azure SDK, Pydantic, etc.)
        critical_result = self._validate_critical_imports()
        validation_result['critical_imports'] = critical_result
        if not critical_result['success']:
            validation_result['success'] = False
        
        # Validate discovered application modules  
        app_result = self._validate_discovered_modules(discovered_modules)
        validation_result['application_modules'] = app_result
        if not app_result['success']:
            validation_result['success'] = False
        
        # Record validation results in registry for historical tracking
        registry = self._record_validation_results(registry, validation_result)
        
        # Save updated registry with validation history
        self._save_module_registry(registry)
        
        # Cache results for performance
        self._last_validation = validation_result
        self._validation_timestamp = datetime.now(timezone.utc)
        
        # Log summary with auto-discovery info
        status_icon = "✅" if validation_result['success'] else "❌"
        failed_count = len(critical_result['failed']) + len(app_result['failed'])
        warning_count = len(validation_result['warnings'])
        discovered_count = len(discovered_modules)
        
        self.logger.info(f"{status_icon} Import validation complete - Success: {validation_result['success']}, Failed: {failed_count}, Warnings: {warning_count}, Auto-discovered: {discovered_count}")
        
        return validation_result
    
    def _validate_critical_imports(self) -> Dict[str, Any]:
        """
        Validate critical dependencies required for Azure Functions operation.
        
        Returns:
            Dict with validation results for critical imports.
        """
        self.logger.debug(f"🔧 Validating critical imports")
        
        critical_modules = [
            # Azure SDK Core
            ('azure.functions', 'Azure Functions runtime'),
            ('azure.identity', 'Azure authentication'),
            ('azure.storage.queue', 'Azure Storage Queue client'),
            
            # Pydantic for schema validation
            ('pydantic', 'Pydantic data validation'),
            
            # Core Python modules  
            ('json', 'JSON processing'),
            ('logging', 'Python logging'),
            ('os', 'Operating system interface'),
            ('sys', 'System-specific parameters')
        ]
        
        result = {
            'success': True,
            'failed': [],
            'details': {}
        }
        
        for module_name, description in critical_modules:
            try:
                __import__(module_name)
                self.logger.debug(f"✅ {module_name} - {description}")
                result['details'][module_name] = {'status': 'success', 'description': description}
                
            except ImportError as e:
                error_msg = f"Failed to import {module_name}: {str(e)}"
                self.logger.error(f"❌ {error_msg}")
                
                result['success'] = False
                result['failed'].append(module_name)
                result['details'][module_name] = {
                    'status': 'failed',
                    'description': description,
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
                
            except Exception as e:
                error_msg = f"Unexpected error importing {module_name}: {str(e)}"
                self.logger.error(f"⚠️ {error_msg}")
                
                result['details'][module_name] = {
                    'status': 'warning',
                    'description': description,
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
        
        return result
    
    def _validate_discovered_modules(self, discovered_modules: List[Tuple[str, str]]) -> Dict[str, Any]:
        """
        Validate discovered application modules.
        
        Args:
            discovered_modules: List of (module_name, description) tuples from auto-discovery.
            
        Returns:
            Dict with validation results for application modules.
        """
        self.logger.debug(f"📦 Validating {len(discovered_modules)} auto-discovered modules")
        
        result = {
            'success': True,
            'failed': [],
            'details': {}
        }
        
        for module_name, description in discovered_modules:
            try:
                __import__(module_name)
                self.logger.debug(f"✅ {module_name} - {description}")
                result['details'][module_name] = {'status': 'success', 'description': description}
                
            except ImportError as e:
                error_msg = f"Failed to import {module_name}: {str(e)}"
                self.logger.warning(f"⚠️ {error_msg}")
                
                result['success'] = False
                result['failed'].append(module_name)
                result['details'][module_name] = {
                    'status': 'failed',
                    'description': description,
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
                
            except Exception as e:
                error_msg = f"Unexpected error importing {module_name}: {str(e)}"
                self.logger.warning(f"⚠️ {error_msg}")
                
                result['details'][module_name] = {
                    'status': 'warning', 
                    'description': description,
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
        
        return result
    
    def _get_environment_info(self) -> Dict[str, Any]:
        """
        Gather environment information for debugging and context.
        
        Returns:
            Dict with environment details.
        """
        return {
            'python_version': sys.version,
            'platform': sys.platform,
            'is_azure_functions': self.is_azure_functions,
            'force_validation': self.force_validation,
            'environment_variables': {
                'AZURE_FUNCTIONS_ENVIRONMENT': os.getenv('AZURE_FUNCTIONS_ENVIRONMENT'),
                'FUNCTIONS_WORKER_RUNTIME': os.getenv('FUNCTIONS_WORKER_RUNTIME'),
                'VALIDATE_IMPORTS': os.getenv('VALIDATE_IMPORTS'),
                'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO')
            }
        }
    
    def ensure_startup_ready(self) -> None:
        """
        Fail-fast validation for application startup.
        
        Validates critical imports and raises ImportError if any critical dependencies
        are missing. Only runs in Azure Functions environment or when explicitly enabled.
        
        Raises:
            ImportError: If critical dependencies are missing and validation is enabled.
        """
        # Only validate in Azure Functions or when explicitly enabled
        if not (self.is_azure_functions or self.force_validation):
            self.logger.debug(f"💻 Startup validation skipped - not in Azure Functions environment")
            return
        
        self.logger.info(f"🚀 Starting fail-fast startup validation")
        
        validation_result = self.validate_all_imports()
        
        if not validation_result['success']:
            critical_failures = validation_result['critical_imports']['failed']
            app_failures = validation_result['application_modules']['failed']
            
            error_details = []
            
            if critical_failures:
                error_details.append(f"Critical imports failed: {', '.join(critical_failures)}")
                
            if app_failures:
                error_details.append(f"Application modules failed: {', '.join(app_failures)}")
            
            error_msg = f"Startup validation failed - {'; '.join(error_details)}"
            
            self.logger.error(f"🔥 STARTUP FAILURE: {error_msg}")
            self.logger.error(f"📋 Full validation details: {validation_result}")
            
            raise ImportError(error_msg)
        
        self.logger.info(f"✅ Startup validation successful - all critical dependencies available")
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status including import validation.
        
        Used by health check endpoint to provide detailed system status.
        
        Returns:
            Dict with health status structure:
            {
                'status': 'healthy|unhealthy|error',
                'timestamp': str,
                'imports': Dict (validation results),
                'overall_success': bool,
                'summary': str
            }
        """
        try:
            self.logger.debug(f"🏥 Generating health status report")
            
            validation_result = self.validate_all_imports()
            
            health_status = {
                'status': 'healthy' if validation_result['success'] else 'unhealthy',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'imports': validation_result,
                'overall_success': validation_result['success'],
                'summary': self._generate_health_summary(validation_result)
            }
            
            status_icon = "🟢" if health_status['status'] == 'healthy' else "🔴"
            self.logger.info(f"{status_icon} Health status generated - Status: {health_status['status']}")
            
            return health_status
            
        except Exception as e:
            error_msg = f"Error generating health status: {str(e)}"
            self.logger.error(f"💥 {error_msg}")
            
            return {
                'status': 'error',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': error_msg,
                'traceback': traceback.format_exc(),
                'overall_success': False,
                'summary': f"Health check system error: {str(e)}"
            }
    
    def _generate_health_summary(self, validation_result: Dict[str, Any]) -> str:
        """
        Generate human-readable summary of health status.
        
        Args:
            validation_result: Results from validate_all_imports().
            
        Returns:
            str: Summary message for health status.
        """
        if validation_result['success']:
            return "All imports successful, system ready for operation"
        
        critical_failed = len(validation_result['critical_imports']['failed'])
        app_failed = len(validation_result['application_modules']['failed'])
        warnings = len(validation_result['warnings'])
        
        issues = []
        if critical_failed > 0:
            issues.append(f"{critical_failed} critical import failures")
        if app_failed > 0:
            issues.append(f"{app_failed} application module failures")
        if warnings > 0:
            issues.append(f"{warnings} warnings")
        
        return f"System issues detected: {', '.join(issues)}"


# Global singleton instance for application use
validator = ImportValidator()