# Project File Index

**Azure Geospatial ETL Pipeline - Root Directory Files**

*Generated: 2025-08-29*

## 📁 File Overview

This document provides a comprehensive index of all files in the root directory of the rmhgeoapi Azure Functions project, organized by category with descriptions of their contents and purposes.

---

## 🚀 **Core Application Files**

### **function_app.py**
- **Primary Azure Functions entry point**
- HTTP triggers for job submission (`/api/jobs/{operation_type}`)
- Queue triggers for job and task processing (`geospatial-jobs`, `geospatial-tasks`)
- Timer triggers for poison queue monitoring
- Controller routing for Pydantic Job→Task architecture
- **Status**: Production-ready with hello_world controller implementation

### **host.json**
- **Azure Functions runtime configuration**
- Logging levels and Application Insights setup
- Queue processing settings (batch size: 16, max dequeue: 5)
- Function timeout configuration (5 minutes)
- Extension bundle configuration for Azure Functions v4

### **requirements.txt**
- **Python package dependencies**
- Azure SDK packages (functions, storage, identity, data-tables)
- Geospatial libraries (rasterio, rio-cogeo)
- **Pydantic v2+ for strong typing discipline**
- PostgreSQL driver (psycopg[binary])

---

## ⚙️ **Configuration Files**

### **config.py**
- **Strongly typed configuration management with Pydantic v2**
- Centralized environment variable validation and documentation
- Azure storage, PostgreSQL, and queue configuration
- Single source of truth for all application settings
- Built-in validation with clear error messages


### **local.settings.json**
- **Local development configuration**
- Environment variables for Azure Functions local runtime
- Managed identity configuration for storage services
- **Contains sensitive data - not for production deployment**

### **local.settings.example.json**
- **Template for local development setup**
- Example configuration without sensitive values
- Reference for required environment variables

### **INFRA_CONFIG.md**
- **Azure infrastructure documentation**
- Function app configuration (rmhgeoapibeta)
- Storage account setup with managed identity
- Environment variables and RBAC permissions
- Local development setup instructions

---

## 🏗️ **Architecture & Models**

### **model_core.py**
- **Core Pydantic models for Job→Task architecture**
- JobRecord, TaskRecord, JobQueueMessage, TaskQueueMessage classes
- JobExecutionContext and StageExecutionContext for orchestration
- Strong typing definitions with validation

### **model_job_base.py**
- **Base job model definitions**
- Abstract job parameter models
- Job status and lifecycle management
- Validation helpers for job creation

### **model_stage_base.py**
- **Stage-based workflow models**
- StageDefinition and stage orchestration classes
- Sequential stage execution patterns
- Stage result aggregation models

### **model_task_base.py**
- **Task execution models**
- TaskDefinition and task parameter validation
- Task result models and completion detection
- Distributed task coordination classes

---

## 🎛️ **Controllers (Job→Task Pattern)**

### **controller_base.py**
- **Abstract base controller for all job types**
- Workflow definition integration and parameter validation
- Job ID generation (SHA256 hash for idempotency)
- Stage orchestration and task creation patterns
- **Core architecture foundation for extensibility**

### **controller_hello_world.py**
- **Hello World controller implementation**
- Demonstrates complete Job→Task workflow
- Multi-task creation with parameter validation (n parameter)
- Result aggregation and completion detection
- **Status**: Fully implemented and tested

---

## 📋 **Schema & Validation**

### **schema_core.py**
- **Core schema definitions for strong typing**
- Parameter validation schemas
- Error handling and validation patterns
- Type safety enforcement classes

### **schema_workflow.py**
- **Workflow definition schemas**
- Stage-based workflow validation
- Operation type definitions and routing
- Parameter schema validation per workflow stage

### **validator_schema.py**
- **Schema validation utilities**
- Custom validators for geospatial parameters
- Input sanitization and type coercion
- Validation error handling and reporting

---

## 🔧 **Services & Processing**

### **service_hello_world.py**
- **Hello World service implementation**
- Demonstrates service layer patterns
- Task processing and result generation
- **Status**: Implementation for Job→Task architecture

### **adapter_storage.py**
- **Storage service adapter**
- Azure Blob Storage abstraction layer
- Managed identity credential handling
- Storage operation wrappers and utilities

### **repository_data.py**
- **Data repository patterns**
- Azure Table Storage abstractions
- Job and task record management
- Query operations and data persistence

---

## 🛠️ **Utilities**

### **util_completion.py**
- **Job completion orchestration utilities**
- Distributed completion detection ("last task turns out the lights")
- Result aggregation patterns
- Completion status management

### **util_logger.py**
- **Centralized logging configuration**
- Azure Application Insights integration
- Structured logging for debugging
- Performance and error tracking


---

## 📚 **Documentation**

### **CLAUDE.md**
- **Primary project context and instructions for Claude AI**
- Architecture overview and current implementation status
- Development philosophy and coding standards
- **Critical reference for understanding project structure**

### **CONFIGURATION_USAGE.md**
- **Comprehensive configuration usage guide**
- Strongly typed configuration examples with Pydantic v2
- Environment variable documentation and validation
- Migration guide from scattered configuration approach

### **DEBUG_ARCHITECTURE_STATUS.md** ⭐ NEW
- **Production debugging completion status (Aug 29, 2025)**
- Systematic resolution of 6 critical architecture issues
- Comprehensive debug logging methodology with visual indicators
- Enum handling fixes, job ID determinism, parameter flow validation

### **PROJECT_FILE_INDEX.md**
- **This document - comprehensive file catalog**
- Organized directory listing with file descriptions
- Status tracking for implementation progress
- Architecture overview and file relationships

### **FILE_NAMING_CONVENTION.md**
- **Project file naming standards**
- Module prefix conventions (controller_, service_, model_, etc.)
- Naming patterns for consistency
- File organization guidelines

### **HELLO_WORLD_IMPLEMENTATION_PLAN.md**
- **Implementation documentation for hello_world controller**
- Step-by-step implementation details
- Testing and validation procedures
- Architecture demonstration patterns

### **STRONG_TYPING_ARCHITECTURE_STATUS.md**
- **Strong typing implementation status**
- Pydantic v2 integration documentation
- Type safety enforcement patterns
- Migration from weak typing to strong typing discipline

### **consolidated_redesign.md**
- **Architecture redesign documentation**
- Job→Stage→Task pattern specifications
- Controller orchestration patterns
- **Historical reference for architecture evolution**

### **redesign.md**
- **Earlier redesign documentation**
- Architecture evolution history
- Design decision rationale
- **Historical reference**

---

## 🔨 **Utility Scripts**

### **FIX_APP_SETTINGS.sh**
- **Shell script for Azure Function App configuration**
- Environment variable deployment automation
- Configuration synchronization utilities
- **Production deployment helper**

---

## 📦 **Archive Files**

### **Archive.zip**
- **Archived previous implementations**
- Historical code versions
- **Reference only - not part of active codebase**

### **webapp_logs.zip**
- **Archived application logs**
- Historical debugging information
- **Reference for troubleshooting patterns**

---

## 🏷️ **System Files**

### **__init__.py**
- **Python package initialization**
- Module export definitions
- Package-level configuration

---

## 📊 **File Status Summary**

| Category | Files | Status |
|----------|-------|---------|
| **Core Application** | 3 | ✅ Production Ready |
| **Configuration** | 4 | ✅ Complete with Pydantic v2 Strong Typing |
| **Architecture & Models** | 4 | ✅ Strong Typing Implemented |
| **Controllers** | 2 | 🔄 Hello World Complete, Others Pending |
| **Schema & Validation** | 3 | ✅ Pydantic v2 Integration |
| **Services & Processing** | 3 | 🔄 Partial Implementation |
| **Utilities** | 2 | ✅ Core Utils Complete |
| **Documentation** | 9 | ✅ Comprehensive + Debug Status |
| **Scripts & Archives** | 3 | ✅ Support Files |

| **System Files** | 1 | ✅ Support Files |

**Total Files: 33**

---

## 🎯 **Key Architecture Patterns**

1. **Pydantic Job→Task Architecture**: Strong typing with workflow definitions
2. **Controller Pattern**: Orchestration layer with parameter validation  
3. **Managed Identity**: Azure authentication without connection strings
4. **Queue-Based Processing**: Asynchronous job and task execution
5. **Distributed Completion**: "Last task turns out the lights" pattern

---

## 🚨 **Development Notes**

- **No Backward Compatibility**: Explicit error handling over fallbacks
- **Strong Typing Discipline**: Pydantic v2 enforcement throughout
- **Production Function App**: rmhgeoapibeta (ONLY active deployment)
- **Resource Group**: rmhazure_rg
- **Storage Account**: rmhazuregeo with managed identity

---

*This index reflects the current state of the Azure Geospatial ETL Pipeline as of August 29, 2025. For the most up-to-date architecture information, see CLAUDE.md.*