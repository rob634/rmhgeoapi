# BaseController Annotated Refactoring Plan

**Date**: 26 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Categorize every BaseController method by repository usage and future home

## Architecture Decision: Composition Over Inheritance

**Why Composition?**
- Parallel queue systems (Storage Queue vs Service Bus) need different implementations
- Repository usage patterns show clear service boundaries
- Testing individual components is easier than 2,290-line God Classes
- Teams can work on different components independently

**What Stays Inherited?**
- Abstract methods (define the contract)
- ID generation (uses controller's job_type)
- Parameter validation (controller-specific logic)

## Annotated BaseController Methods

```python
class BaseController(ABC):

    def __init__(self):
        """
        CATEGORY: Constructor
        DESTINATION: Stays in BaseController
        REASON: Basic initialization, sets up logging
        REPOSITORIES: None
        """
        pass

    # ========================================================================
    # CATEGORY 1: ABSTRACT METHODS - Stay in BaseController (INHERITANCE)
    # ========================================================================

    @abstractmethod
    def get_job_type(self) -> str:
        """
        CATEGORY: Abstract Method
        DESTINATION: Stays in BaseController
        REASON: Core contract, must be implemented by concrete controllers
        REPOSITORIES: None
        """
        pass

    @abstractmethod
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        CATEGORY: Abstract Method / Validation
        DESTINATION: Stays in BaseController
        REASON: Controller-specific validation logic
        REPOSITORIES: None
        """
        pass

    @abstractmethod
    def create_stage_tasks(self, stage_number: int, job_id: str,
                          job_parameters: Dict[str, Any],
                          previous_stage_results: Optional[List[Dict[str, Any]]]) -> List[TaskDefinition]:
        """
        CATEGORY: Abstract Method
        DESTINATION: Stays in BaseController
        REASON: Core business logic, controller-specific task creation
        REPOSITORIES: None
        """
        pass

    @abstractmethod
    def should_advance_stage(self, job_id: str, current_stage: int,
                           stage_results: Dict[str, Any]) -> bool:
        """
        CATEGORY: Abstract Method
        DESTINATION: Stays in BaseController
        REASON: Controller-specific stage progression logic
        REPOSITORIES: None
        """
        pass

    @abstractmethod
    def aggregate_job_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        CATEGORY: Abstract Method
        DESTINATION: Stays in BaseController
        REASON: Controller-specific result aggregation
        REPOSITORIES: None
        """
        pass

    # ========================================================================
    # CATEGORY 2: ID GENERATION - Stay in BaseController (INHERITANCE)
    # ========================================================================

    def generate_job_id(self, parameters: Dict[str, Any]) -> str:
        """
        CATEGORY: ID Generation
        DESTINATION: Stays in BaseController
        REASON: Uses self.job_type, core to idempotency
        REPOSITORIES: None
        PATTERN: SHA256(job_type + params) for deterministic IDs
        """
        # Lines 350-374
        pass

    def generate_task_id(self, job_id: str, stage: int, semantic_index: str) -> str:
        """
        CATEGORY: ID Generation
        DESTINATION: Stays in BaseController
        REASON: Semantic naming is controller-specific
        REPOSITORIES: None
        PATTERN: {job_id[:8]}-s{stage}-{semantic_index}
        """
        # Lines 376-421
        pass

    # ========================================================================
    # CATEGORY 3: VALIDATION - Stay in BaseController (INHERITANCE)
    # ========================================================================

    def validate_stage_parameters(self, stage_number: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        CATEGORY: Validation
        DESTINATION: Stays in BaseController
        REASON: Stage-specific parameter validation
        REPOSITORIES: None
        """
        # Lines 458-471
        pass

    # ========================================================================
    # CATEGORY 4: STATE MANAGEMENT - Move to StateManager (COMPOSITION)
    # ========================================================================

    def complete_job(self, job_id: str, all_task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        CATEGORY: State Management
        DESTINATION: StateManager (composition)
        REASON: Database operation with advisory locks
        REPOSITORIES: job_repo, task_repo (via RepositoryFactory)
        PATTERN: Atomic job completion with PostgreSQL
        """
        # Lines 1006-1050
        # Uses: repos = RepositoryFactory.create_repositories()
        # Uses: job_repo.complete_job(job_id, final_result)
        pass

    def _handle_stage_completion(self, job_id: str, stage: int,
                                job_repo: Any,
                                stage_completion_repo: 'StageCompletionRepository') -> Dict[str, Any]:
        """
        CATEGORY: State Management
        DESTINATION: StateManager (composition)
        REASON: Critical SQL operations with advisory locks
        REPOSITORIES: job_repo, stage_completion_repo
        PATTERN: "Last task turns out lights" with atomic checks
        CRITICAL: Must be shared between Queue Storage and Service Bus!
        """
        # Lines 1989-2208
        # Uses: stage_completion_repo.check_job_completion(job_id)
        # Uses: stage_completion_repo.advance_job_stage(job_id, next_stage)
        pass

    def _create_completion_context(self, job_id: str,
                                 all_task_results: List[Dict[str, Any]]) -> JobExecutionContext:
        """
        CATEGORY: State Management / Context Creation
        DESTINATION: StateManager (composition)
        REASON: Part of job completion flow
        REPOSITORIES: job_repo (for job record retrieval)
        """
        # Lines 1051-1114
        pass

    def _validate_and_get_stage_results(self, job_id: str,
                                       job_repo: Any) -> Dict[int, Dict[str, Any]]:
        """
        CATEGORY: State Management
        DESTINATION: StateManager (composition)
        REASON: Retrieves and validates stage results from DB
        REPOSITORIES: job_repo
        PATTERN: Handles PostgreSQL JSON key conversion (int→string)
        """
        # Lines 1115-1207
        pass

    def get_completed_stages(self, job_id: str) -> List[int]:
        """
        CATEGORY: State Management / Monitoring
        DESTINATION: StateManager (composition)
        REASON: Database query for completed stages
        REPOSITORIES: task_repo (via RepositoryFactory)
        """
        # Lines 983-1005
        pass

    def get_stage_status(self, job_id: str) -> Dict[int, str]:
        """
        CATEGORY: State Management / Monitoring
        DESTINATION: StateManager (composition)
        REASON: Database query for stage statuses
        REPOSITORIES: task_repo (via RepositoryFactory)
        """
        # Lines 955-982
        pass

    def create_job_record(self, job_id: str, parameters: Dict[str, Any]) -> JobRecord:
        """
        CATEGORY: State Management
        DESTINATION: StateManager (composition)
        REASON: Creates record in PostgreSQL
        REPOSITORIES: job_repo (via RepositoryFactory)
        SQL: INSERT INTO jobs with initial QUEUED status
        """
        # Lines 697-733
        # Uses: repos = RepositoryFactory.create_repositories()
        # Uses: job_repo.create_job_from_params()
        pass

    # ========================================================================
    # CATEGORY 5: QUEUE PROCESSING - Move to QueueProcessor (COMPOSITION)
    # ========================================================================

    def process_job_queue_message(self, job_message: 'JobQueueMessage') -> Dict[str, Any]:
        """
        CATEGORY: Queue Processing
        DESTINATION: QueueStorageProcessor (composition)
        REASON: 253 lines of Queue Storage specific logic!
        REPOSITORIES: job_repo, task_repo, stage_completion_repo
        PATTERN: Processes job messages from Azure Storage Queue
        """
        # Lines 1494-1747 (253 lines!)
        pass

    def process_task_queue_message(self, task_message: 'TaskQueueMessage') -> Dict[str, Any]:
        """
        CATEGORY: Queue Processing
        DESTINATION: QueueStorageProcessor (composition)
        REASON: 240 lines of Queue Storage specific logic!
        REPOSITORIES: task_repo, stage_completion_repo
        PATTERN: Processes task messages, calls SQL completion
        NOTE: Must extract SQL logic to StateManager first!
        """
        # Lines 1748-1988 (240 lines!)
        # CRITICAL: Lines 1863-1938 (SQL completion) → StateManager
        pass

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        CATEGORY: Queue Processing
        DESTINATION: QueueStorageProcessor (composition)
        REASON: Azure Storage Queue specific operations
        REPOSITORIES: queue_repo (via RepositoryFactory)
        USES: QueueRepository singleton for queue access
        """
        # Lines 745-806
        # Uses: queue_repo = RepositoryFactory.create_queue_repository()
        # Uses: queue_repo.send_message(queue_name, message)
        pass

    def create_job_queue_message(self, job_id: str, parameters: Dict[str, Any],
                               stage: int = 1) -> JobQueueMessage:
        """
        CATEGORY: Queue Processing
        DESTINATION: QueueStorageProcessor (composition)
        REASON: Creates Queue-specific message format
        REPOSITORIES: None
        """
        # Lines 734-744
        pass

    def _safe_mark_job_failed(self, job_id: str, error_msg: str,
                            job_repo=None) -> None:
        """
        CATEGORY: Queue Processing / Error Handling
        DESTINATION: QueueStorageProcessor (composition)
        REASON: Queue-specific error recovery
        REPOSITORIES: job_repo (optional)
        """
        # Lines 2209-2249
        pass

    def _safe_mark_task_failed(self, task_id: str, error_msg: str,
                             task_repo=None) -> None:
        """
        CATEGORY: Queue Processing / Error Handling
        DESTINATION: QueueStorageProcessor (composition)
        REASON: Queue-specific error recovery
        REPOSITORIES: task_repo (optional)
        """
        # Lines 2250-2289
        pass

    # ========================================================================
    # CATEGORY 6: WORKFLOW MANAGEMENT - Move to WorkflowManager (COMPOSITION)
    # ========================================================================

    def get_workflow_stage_definition(self, stage_number: int):
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Workflow configuration lookup
        REPOSITORIES: None (uses self.workflow_definition)
        """
        # Lines 472-475
        pass

    def get_next_stage_number(self, current_stage: int) -> Optional[int]:
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Stage progression logic
        REPOSITORIES: None
        """
        # Lines 476-480
        pass

    def is_final_stage(self, stage_number: int) -> bool:
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Workflow boundary check
        REPOSITORIES: None (uses self.workflow_definition)
        """
        # Lines 481-489
        pass

    def supports_dynamic_orchestration(self) -> bool:
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Workflow capability check
        REPOSITORIES: None
        """
        # Lines 490-501
        pass

    def parse_orchestration_instruction(self, stage_results: Dict[str, Any]) -> Optional['OrchestrationInstruction']:
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Dynamic workflow parsing
        REPOSITORIES: None
        """
        # Lines 502-583
        pass

    def create_tasks_from_orchestration(self, orchestration: 'OrchestrationInstruction',
                                       job_id: str, stage: int) -> List[TaskDefinition]:
        """
        CATEGORY: Workflow Management
        DESTINATION: WorkflowManager (composition)
        REASON: Dynamic task creation from orchestration
        REPOSITORIES: None
        """
        # Lines 584-661
        pass

    def process_job_stage(self, job_record: 'JobRecord', stage: int,
                        parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        CATEGORY: Workflow Management + Queue Processing
        DESTINATION: Split between WorkflowManager and QueueProcessor
        REASON: Mixed concerns - orchestration + queue operations
        REPOSITORIES: task_repo, queue_repo
        NOTE: This is a GOD METHOD (285 lines) - needs major refactoring!
        """
        # Lines 1208-1493 (285 lines!)
        pass

    # ========================================================================
    # CATEGORY 7: CONTEXT CREATION - Move to ContextFactory (COMPOSITION)
    # ========================================================================

    def create_job_context(self, job_id: str, parameters: Dict[str, Any],
                         current_stage: int = 1) -> JobExecutionContext:
        """
        CATEGORY: Context Creation
        DESTINATION: ContextFactory (composition)
        REASON: Factory pattern for context objects
        REPOSITORIES: None (uses self.workflow_definition)
        """
        # Lines 662-676
        pass

    def create_stage_context(self, job_context: JobExecutionContext,
                           stage_number: int) -> StageExecutionContext:
        """
        CATEGORY: Context Creation
        DESTINATION: ContextFactory (composition)
        REASON: Factory pattern for context objects
        REPOSITORIES: None (uses self.workflow_definition)
        """
        # Lines 677-696
        pass

    # ========================================================================
    # CATEGORY 8: MONITORING - Move to MonitoringService (COMPOSITION)
    # ========================================================================

    def list_stage_tasks(self, job_id: str, stage_number: int) -> List[Dict[str, Any]]:
        """
        CATEGORY: Monitoring
        DESTINATION: MonitoringService (composition)
        REASON: Read-only status queries
        REPOSITORIES: task_repo (via RepositoryFactory)
        """
        # Lines 807-829
        pass

    def get_job_tasks(self, job_id: str) -> Dict[int, List[Dict[str, Any]]]:
        """
        CATEGORY: Monitoring
        DESTINATION: MonitoringService (composition)
        REASON: Read-only status queries
        REPOSITORIES: task_repo (via RepositoryFactory)
        """
        # Lines 830-853
        pass

    def get_task_progress(self, job_id: str) -> Dict[str, Any]:
        """
        CATEGORY: Monitoring
        DESTINATION: MonitoringService (composition)
        REASON: Read-only progress tracking
        REPOSITORIES: job_repo, task_repo (via RepositoryFactory)
        """
        # Lines 854-932
        pass

    def list_job_stages(self) -> List[Dict[str, Any]]:
        """
        CATEGORY: Monitoring / Workflow
        DESTINATION: MonitoringService or WorkflowManager
        REASON: Lists available stages from workflow
        REPOSITORIES: None (uses self.workflow_definition)
        """
        # Lines 933-954
        pass

    def aggregate_stage_results(self, job_id: str, stage_number: int,
                              task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        CATEGORY: Result Aggregation / Monitoring
        DESTINATION: Could stay in BaseController OR MonitoringService
        REASON: Has @enforce_contract decorator, uses StageResultContract
        REPOSITORIES: None (pure data transformation)
        NOTE: Default implementation, can be overridden
        """
        # Lines 224-309
        pass

    def __repr__(self):
        """
        CATEGORY: Utility
        DESTINATION: Stays in BaseController
        REASON: String representation
        REPOSITORIES: None
        """
        # Line 2290
        pass
```

## Summary: Repository Usage Patterns

### Components by Repository Usage:

#### StateManager (Uses job_repo, task_repo, stage_completion_repo)
- All job/task state mutations
- Advisory lock operations
- Stage completion logic
- Job completion
- Database record creation

#### QueueStorageProcessor (Uses queue_repo primarily)
- Queue message processing
- Error recovery
- Message creation and sending
- 500+ lines of queue-specific logic

#### WorkflowManager (No repositories - configuration only)
- Workflow definitions
- Stage progression rules
- Dynamic orchestration
- Task creation from orchestration

#### MonitoringService (Uses job_repo, task_repo read-only)
- Status queries
- Progress tracking
- Task listings
- Read-only operations

#### ContextFactory (No repositories)
- Context object creation
- Pure data transformation

## Refactoring Priority:

1. **Extract StateManager FIRST** - Critical for Service Bus (advisory locks)
2. **Extract QueueStorageProcessor** - Biggest win (500+ lines)
3. **Extract WorkflowManager** - Clean separation of concerns
4. **Extract MonitoringService** - Nice to have
5. **Extract ContextFactory** - Low priority

## Final Architecture:

```python
class BaseController(ABC):
    """Slim base with only inherited methods"""
    # 5 abstract methods
    # 2 ID generation methods
    # 2 validation methods
    # Total: ~200 lines

    def __init__(self):
        # Composition!
        self.state_manager = StateManager()
        self.workflow_manager = WorkflowManager(self.get_job_type())
        self.monitoring = MonitoringService()
        self.context_factory = ContextFactory()
        # Queue processor injected by concrete class

class QueueStorageController(BaseController):
    def __init__(self):
        super().__init__()
        self.queue_processor = QueueStorageProcessor()

class ServiceBusController(BaseController):
    def __init__(self):
        super().__init__()
        self.queue_processor = ServiceBusProcessor()
```

This gives us:
- Clean separation by repository usage
- Service Bus gets StateManager (critical for advisory locks)
- No God Classes
- Testable components
- Parallel queue strategies!