# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# EPOCH: 3 - DEPRECATED ⚠️
# STATUS: Replaced by Epoch 4 CoreMachine
# MIGRATION: Will be archived after Storage Queue triggers migrated
# PURPOSE: DEPRECATED - Service Bus base controller with God Class inheritance
# EXPORTS: ServiceBusBaseController - Base for Service Bus controllers (DEPRECATED)
# INTERFACES: Extends BaseController (God Class anti-pattern)
# PYDANTIC_MODELS: Uses same models as BaseController
# DEPENDENCIES: controller_base (God Class), repositories
# SOURCE: DEPRECATED - Replaced by clean architecture components
# SCOPE: DEPRECATED - Use clean architecture instead
# VALIDATION: Same as BaseController
# PATTERNS: God Class anti-pattern (DEPRECATED)
# ENTRY_POINTS: DEPRECATED - Use controller_service_bus_hello.py instead
# INDEX: ServiceBusBaseController:50
# ============================================================================

"""
DEPRECATED: Service Bus Base Controller with God Class

This file is kept for reference but should NOT be used.
Use the clean architecture implementation instead:
- controller_service_bus_hello.py (clean HelloWorld)
- service_bus_list_processor.py (clean list-then-process base)

The ServiceBusBaseController inherits from BaseController which is
a 2,290-line God Class. This has been replaced with clean architecture
that uses composition instead of massive inheritance.

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025 - DEPRECATED
"""

# DEPRECATED: This entire file is deprecated
# Use clean architecture components instead:
# - CoreController (minimal inheritance)
# - StateManager (database operations)
# - OrchestrationManager (dynamic tasks)
# - ServiceBusListProcessor (list-then-process pattern)

"""
The old ServiceBusBaseController has been removed.
It inherited from the 2,290-line BaseController God Class.

For new Service Bus controllers, use:
1. controller_service_bus_hello.py - Clean HelloWorld implementation
2. service_bus_list_processor.py - Base for list-then-process patterns
3. CoreController + StateManager + OrchestrationManager - Clean components

This achieves the same functionality without God Class inheritance.
"""