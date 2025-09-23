# Registry Pattern Refactoring Guide
## From Import-Time Decorators to Modular Architecture

**Date**: September 2025 
**Purpose**: Restructure registration pattern to enable future Function App splitting  
**Current State**: Working but tightly coupled via decorator registration  
**Target State**: Modular, loosely coupled architecture ready for microservice split

---

## 🔴 Current Problem: Decorator-Based Registration

### The Issue
Our current architecture uses decorators that register at import time:

```python
# Current problematic pattern
@JobRegistry.register("hello_world")  # ← Executes at import!
class HelloWorldController(BaseController):
    pass
```

### Why This Is Problematic

1. **Import-Time Side Effects**
   - Registration happens when file is imported, not when we want it
   - Azure Functions initialization sequence conflicts
   - Can't control registration order

2. **Tight Coupling**
   - Global registries create hidden dependencies
   - All controllers must be present for any to work
   - Can't selectively load modules

3. **Prevents Clean Splitting**
   - Registry assumes all controllers exist in same app
   - Cross-module dependencies through shared registry
   - Would require major refactoring to split

4. **Worker Reuse Issues**
   - Global state persists across invocations
   - Registration might happen multiple times
   - Unpredictable behavior when workers restart

---

## ✅ Solution: Module-Based Configuration Pattern

### Core Principles

1. **No import-time side effects** - Classes are just classes
2. **Explicit registration** - App decides what to register and when
3. **Module isolation** - Each module is self-contained
4. **Registry per app** - Each Function App has its own registry

### New Architecture

```
rmhgeoapi/
├── core/                      # Minimal shared code
│   ├── interfaces.py         # ABCs only
│   ├── schemas.py            # Base Pydantic models
│   └── exceptions.py         # Common exceptions
│
├── modules/                   # Self-contained modules
│   ├── __init__.py           # Empty or minimal
│   ├── raster/
│   │   ├── __init__.py      # Empty
│   │   ├── config.py        # Module configuration
│   │   ├── controllers.py   # No decorators
│   │   ├── services.py      # Business logic
│   │   └── schemas.py       # Module-specific models
│   │
│   ├── vector/
│   │   └── [same structure]
│   │
│   └── orchestration/
│       ├── config.py
│       ├── controllers.py   # Job submission, monitoring
│       └── services.py
│
└── apps/                      # Current monolith, future separate
    └── unified/
        ├── function_app.py   # Registers all modules
        └── registry.py       # App-specific registry
```

---

## 📝 Implementation Steps

### Step 1: Create Module Configuration Pattern

Instead of decorators, each module exports its configuration:

```python
# modules/raster/config.py
from dataclasses import dataclass
from typing import Dict, Type, List

@dataclass
class ModuleConfig:
    """Configuration for a processing module"""
    name: str
    controllers: Dict[str, Type]  # job_type -> Controller class
    services: Dict[str, Type]      # service_name -> Service class
    required_env_vars: List[str]
    dependencies: List[str]        # External libraries

# Export module configuration
RASTER_MODULE = ModuleConfig(
    name="raster",
    controllers={
        "process_cog": COGController,
        "extract_bbox": BBoxController,
    },
    services={
        "gdal_transform": GDALTransformService,
        "cog_validator": COGValidatorService,
    },
    required_env_vars=["BRONZE_CONTAINER", "SILVER_CONTAINER"],
    dependencies=["gdal", "rasterio", "rio-cogeo"]
)
```

### Step 2: Remove Decorators from Controllers

```python
# modules/raster/controllers.py
# BEFORE: 
@JobRegistry.register("process_cog")  # ← DELETE THIS
class COGController(BaseController):
    pass

# AFTER:
class COGController(BaseController):
    """Process Cloud Optimized GeoTIFF"""
    job_type = "process_cog"  # ← Static attribute instead
    
    def validate_parameters(self, params: dict) -> bool:
        # Implementation unchanged
        pass
```

### Step 3: Create App-Level Registry

```python
# apps/unified/registry.py
class AppRegistry:
    """Registry for this specific Function App instance"""
    
    def __init__(self):
        self.controllers = {}
        self.services = {}
        self.modules = {}
    
    def register_module(self, config: ModuleConfig):
        """Register a complete module"""
        self.modules[config.name] = config
        
        # Register controllers
        for job_type, controller_class in config.controllers.items():
            self.controllers[job_type] = controller_class
        
        # Register services
        for service_name, service_class in config.services.items():
            self.services[service_name] = service_class
    
    def get_controller(self, job_type: str):
        """Get controller for job type"""
        if job_type not in self.controllers:
            raise ValueError(f"Unknown job type: {job_type}")
        return self.controllers[job_type]
    
    def validate_environment(self):
        """Ensure all required env vars exist"""
        missing = []
        for module in self.modules.values():
            for var in module.required_env_vars:
                if not os.getenv(var):
                    missing.append(f"{module.name}: {var}")
        
        if missing:
            raise EnvironmentError(f"Missing env vars: {missing}")
```

### Step 4: Explicit Registration in Function App

```python
# apps/unified/function_app.py
import azure.functions as func
from apps.unified.registry import AppRegistry

# Create Function App
app = func.FunctionApp()

# Create registry for this app
registry = AppRegistry()

def initialize_modules():
    """Register all modules for unified development app"""
    # Import module configs (not the modules themselves!)
    from modules.raster.config import RASTER_MODULE
    from modules.vector.config import VECTOR_MODULE
    from modules.orchestration.config import ORCHESTRATION_MODULE
    
    # Register modules explicitly
    registry.register_module(RASTER_MODULE)
    registry.register_module(VECTOR_MODULE)
    registry.register_module(ORCHESTRATION_MODULE)
    
    # Validate environment
    registry.validate_environment()

# Initialize AFTER Azure is ready
initialize_modules()

# HTTP trigger uses registry
@app.function_name(name="SubmitJob")
@app.route(route="jobs/submit/{job_type}")
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    job_type = req.route_params.get('job_type')
    
    # Get controller from registry
    controller_class = registry.get_controller(job_type)
    controller = controller_class()
    
    # Process job
    result = controller.process(req.get_json())
    return func.HttpResponse(json.dumps(result))
```

---

## 🔄 Migration Strategy

### Phase 1: Parallel Implementation (No Breaking Changes)
1. Create new module structure alongside existing code
2. Add module configs without removing decorators
3. Test new registration pattern in development

### Phase 2: Gradual Migration
1. Migrate one controller at a time
2. Remove decorator, add to module config
3. Update tests for each migrated controller

### Phase 3: Cleanup
1. Remove old registry code
2. Delete decorator implementations
3. Update documentation

### Phase 4: Split Preparation
1. Validate no cross-module imports
2. Ensure core/ is truly minimal
3. Test selective module loading

---

## 🚀 Future State: Separate Function Apps

Once refactored, splitting becomes trivial:

```python
# apps/raster/function_app.py (NEW APP)
from apps.raster.registry import AppRegistry
from modules.raster.config import RASTER_MODULE

app = func.FunctionApp()
registry = AppRegistry()

# Only register raster module!
registry.register_module(RASTER_MODULE)

# apps/orchestration/function_app.py (NEW APP)  
from modules.orchestration.config import ORCHESTRATION_MODULE

# Only register orchestration!
registry.register_module(ORCHESTRATION_MODULE)
```

---

## ⚠️ Critical Considerations

### What Goes in Core
- **YES**: Interfaces (ABCs), base exceptions, shared type definitions
- **NO**: Business logic, registries, module-specific code
- **Think**: "Could this be a pip package used by all apps?"

### Module Independence Rules
1. Modules NEVER import from other modules
2. Modules only import from core/
3. Module configs are pure data (no behavior)
4. Services within a module can share code

### Environment Variables
- Each module declares its requirements
- Apps validate at startup (fail fast)
- Future apps only need vars for their modules

---

## 📊 Benefits After Refactoring

1. **Clean Separation**: Each module is independent
2. **Explicit Dependencies**: Clear what each module needs
3. **Testability**: Can test modules in isolation
4. **Deployment Flexibility**: Deploy only what you need
5. **Team Scalability**: Teams own modules, not monoliths
6. **Cost Optimization**: Right-size each Function App
7. **Performance**: Load only required dependencies

---

## 🎯 Success Criteria

- [ ] No decorators with side effects at import time
- [ ] Each module can be imported without registering anything
- [ ] Registry is created per Function App, not global
- [ ] Cross-module imports generate errors
- [ ] Can selectively load subset of modules
- [ ] Environment validation happens at startup
- [ ] No global state shared between modules

---

## Example: Current vs Future

### Current (Problematic)
```python
# All registration happens automatically on import
from controller_hello import HelloWorldController  # Registered!
from controller_raster import RasterController     # Registered!
# Can't prevent registration, can't split easily
```

### Future (Clean)
```python
# apps/orchestration/function_app.py
registry.register_module(ORCHESTRATION_MODULE)  # Only orchestration

# apps/raster/function_app.py  
registry.register_module(RASTER_MODULE)         # Only raster

# apps/unified/function_app.py (dev only)
registry.register_module(ORCHESTRATION_MODULE)  # Register all for dev
registry.register_module(RASTER_MODULE)
registry.register_module(VECTOR_MODULE)
```

---

*This refactoring establishes the foundation for enterprise-scale microservice architecture while maintaining development velocity.*