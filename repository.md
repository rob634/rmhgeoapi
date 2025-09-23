# Singleton & Repository Patterns in Azure Functions
## With Complete Queue Repository Design

**Date**: November 2024  
**Purpose**: Establish clear patterns for singleton usage and repository design  
**Focus**: When to use singletons, why credentials belong in repositories, complete QueueRepository implementation

---

## 🎯 Core Principles

### The Golden Rules

1. **Repositories encapsulate ALL infrastructure concerns** (credentials, connections, retry logic)
2. **Singletons are for expensive resources** (not for registration or configuration discovery)
3. **Controllers orchestrate, Services process, Repositories persist**
4. **One credential instance per resource type per worker**

---

## 🔄 Understanding Singletons in Azure Functions

### How Azure Functions Workers Operate

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Functions Host                   │
├─────────────────────────────────────────────────────────┤
│  Worker Process (Lives 5-20 minutes)                      │
│  ├── Global State (Singletons live here)                 │
│  │   ├── BlobRepository._instance                        │
│  │   ├── QueueRepository._instance                       │
│  │   └── DatabasePool._instance                          │
│  │                                                        │
│  ├── Invocation 1: HTTP Submit Job                       │
│  ├── Invocation 2: Queue Process Task A                  │
│  ├── Invocation 3: Queue Process Task B                  │
│  └── ... (Handles 100s of invocations)                   │
└─────────────────────────────────────────────────────────┘
```

### Why Singletons Matter

**Without Singletons (Bad)**:
```python
Invocation 1: Creates DefaultAzureCredential → 500ms
Invocation 2: Creates DefaultAzureCredential → 500ms  
Invocation 3: Creates DefaultAzureCredential → 500ms
... 100 invocations = 50 seconds wasted!
```

**With Singletons (Good)**:
```python
Invocation 1: Creates DefaultAzureCredential → 500ms
Invocation 2: Reuses existing credential → 0ms
Invocation 3: Reuses existing credential → 0ms
... 100 invocations = 500ms total!
```

---

## 📦 Repository Pattern: Why Credentials Belong Here

### The Repository Responsibility

Repositories are the **boundary between your application and external systems**. They handle:
- Authentication & Authorization
- Connection management
- Retry logic
- Error translation
- Resource pooling

### Anti-Pattern: Credentials in Controllers
```python
# ❌ WRONG - Controller knows about Azure credentials
class JobController:
    def submit_job(self):
        credential = DefaultAzureCredential()  # Infrastructure leak!
        queue_client = QueueServiceClient(...)
        queue_client.send_message(...)
```

**Problems**:
- Controller knows about Azure infrastructure
- Credential created multiple times
- Hard to test (can't mock Azure)
- Violates single responsibility

### Correct Pattern: Credentials in Repository
```python
# ✅ CORRECT - Controller only knows business logic
class JobController:
    def submit_job(self):
        queue_repo = QueueRepository.instance()
        queue_repo.send_job_message(job_message)  # Clean interface!
```

**Benefits**:
- Controller focuses on orchestration
- Credential created once, reused
- Easy to test (mock repository)
- Infrastructure details hidden

---

## 🚀 Complete Queue Repository Design

### Interface Definition

```python
# interfaces/repository.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class IQueueRepository(ABC):
    """
    Interface for queue operations.
    
    All queue operations go through this interface, ensuring
    consistent authentication, error handling, and monitoring.
    """
    
    @abstractmethod
    def send_message(self, queue_name: str, message: BaseModel) -> str:
        """Send a message to specified queue"""
        pass
    
    @abstractmethod
    def receive_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """Receive messages from queue"""
        pass
    
    @abstractmethod
    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str) -> bool:
        """Delete a message from queue"""
        pass
    
    @abstractmethod
    def peek_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """Peek at messages without removing them"""
        pass
    
    @abstractmethod
    def get_queue_length(self, queue_name: str) -> int:
        """Get approximate number of messages in queue"""
        pass
    
    @abstractmethod
    def clear_queue(self, queue_name: str) -> bool:
        """Clear all messages from queue (use with caution)"""
        pass
```

### Implementation

```python
# repositories/queue.py
from azure.storage.queue import QueueServiceClient, QueueClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from typing import Optional, List, Dict, Any
import base64
import json
import logging
from datetime import datetime
from pydantic import BaseModel

from interfaces.repository import IQueueRepository
from config import get_config
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "QueueRepository")


class QueueRepository(IQueueRepository):
    """
    Centralized queue repository with managed authentication.
    
    CRITICAL: This is THE authentication point for all queue operations.
    - Uses DefaultAzureCredential for seamless auth across environments
    - Singleton pattern ensures connection reuse
    - Connection pooling for queue clients
    - Thread-safe implementation
    
    Design Principles:
    - Single source of authentication for all queue operations
    - Automatic retry logic with exponential backoff
    - Consistent error handling and logging
    - Message encoding/decoding handled internally
    
    Usage:
        # Get singleton instance (recommended)
        queue_repo = QueueRepository.instance()
        
        # Or through factory
        queue_repo = RepositoryFactory.create_queue_repository()
    """
    
    _instance: Optional['QueueRepository'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Thread-safe singleton creation"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize once with DefaultAzureCredential"""
        if not hasattr(self, '_initialized'):
            logger.info("🔐 Initializing QueueRepository with DefaultAzureCredential")
            
            try:
                # Create credential ONCE for all queue operations
                self.credential = DefaultAzureCredential()
                
                # Get configuration
                config = get_config()
                self.account_url = config.queue_service_url
                
                # Create service client
                self.queue_service = QueueServiceClient(
                    account_url=self.account_url,
                    credential=self.credential
                )
                
                # Cache for queue clients (created lazily)
                self._queue_clients: Dict[str, QueueClient] = {}
                
                # Configuration
                self.max_retries = 3
                self.retry_delay = 1  # seconds
                
                self._initialized = True
                logger.info("✅ QueueRepository initialized successfully")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize QueueRepository: {e}")
                raise RuntimeError(f"QueueRepository initialization failed: {e}")
    
    @classmethod
    def instance(cls) -> 'QueueRepository':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _get_queue_client(self, queue_name: str) -> QueueClient:
        """
        Get or create a queue client.
        
        Lazily creates and caches queue clients for reuse.
        """
        if queue_name not in self._queue_clients:
            logger.debug(f"📦 Creating queue client for: {queue_name}")
            self._queue_clients[queue_name] = self.queue_service.get_queue_client(queue_name)
            
            # Ensure queue exists
            try:
                self._queue_clients[queue_name].create_queue()
                logger.info(f"✅ Created queue: {queue_name}")
            except ResourceExistsError:
                logger.debug(f"Queue already exists: {queue_name}")
            except Exception as e:
                logger.error(f"❌ Error checking queue {queue_name}: {e}")
                raise
        
        return self._queue_clients[queue_name]
    
    def send_message(self, queue_name: str, message: BaseModel) -> str:
        """
        Send a message to the specified queue.
        
        Args:
            queue_name: Target queue name
            message: Pydantic model to send
            
        Returns:
            Message ID
            
        Raises:
            RuntimeError: If send fails after retries
        """
        queue_client = self._get_queue_client(queue_name)
        
        # Convert Pydantic model to JSON
        message_json = message.model_dump_json()
        
        # Log message details
        logger.info(f"📤 Sending message to queue: {queue_name}")
        logger.debug(f"Message type: {type(message).__name__}")
        logger.debug(f"Message size: {len(message_json)} bytes")
        
        # Send with retry logic
        for attempt in range(self.max_retries):
            try:
                # Azure Queues require base64 encoding for JSON
                encoded_message = base64.b64encode(message_json.encode()).decode()
                
                response = queue_client.send_message(encoded_message)
                
                logger.info(f"✅ Message sent successfully. ID: {response['id']}")
                return response['id']
                
            except Exception as e:
                logger.warning(f"⚠️ Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt == self.max_retries - 1:
                    logger.error(f"❌ Failed to send message after {self.max_retries} attempts")
                    raise RuntimeError(f"Failed to send message to {queue_name}: {e}")
                
                # Exponential backoff
                import time
                time.sleep(self.retry_delay * (2 ** attempt))
    
    def receive_messages(
        self, 
        queue_name: str, 
        max_messages: int = 1,
        visibility_timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Receive messages from queue.
        
        Args:
            queue_name: Queue to receive from
            max_messages: Maximum messages to receive (1-32)
            visibility_timeout: How long to hide messages (seconds)
            
        Returns:
            List of message dictionaries with content and metadata
        """
        queue_client = self._get_queue_client(queue_name)
        
        try:
            messages = queue_client.receive_messages(
                max_messages=max_messages,
                visibility_timeout=visibility_timeout
            )
            
            result = []
            for msg in messages:
                # Decode base64 JSON content
                decoded_content = base64.b64decode(msg.content).decode()
                message_data = json.loads(decoded_content)
                
                result.append({
                    'id': msg.id,
                    'content': message_data,
                    'pop_receipt': msg.pop_receipt,
                    'dequeue_count': msg.dequeue_count,
                    'inserted_on': msg.inserted_on,
                    'expires_on': msg.expires_on
                })
            
            logger.info(f"📥 Received {len(result)} messages from {queue_name}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to receive messages from {queue_name}: {e}")
            raise
    
    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str) -> bool:
        """
        Delete a message from the queue.
        
        Args:
            queue_name: Queue containing the message
            message_id: Message ID
            pop_receipt: Pop receipt from receive operation
            
        Returns:
            True if deleted successfully
        """
        queue_client = self._get_queue_client(queue_name)
        
        try:
            queue_client.delete_message(message_id, pop_receipt)
            logger.debug(f"🗑️ Deleted message {message_id} from {queue_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete message {message_id}: {e}")
            return False
    
    def peek_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at messages without removing them from queue.
        
        Args:
            queue_name: Queue to peek at
            max_messages: Maximum messages to peek (1-32)
            
        Returns:
            List of message dictionaries
        """
        queue_client = self._get_queue_client(queue_name)
        
        try:
            messages = queue_client.peek_messages(max_messages=max_messages)
            
            result = []
            for msg in messages:
                decoded_content = base64.b64decode(msg.content).decode()
                message_data = json.loads(decoded_content)
                
                result.append({
                    'id': msg.id,
                    'content': message_data,
                    'dequeue_count': msg.dequeue_count,
                    'inserted_on': msg.inserted_on
                })
            
            logger.debug(f"👀 Peeked at {len(result)} messages in {queue_name}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to peek messages in {queue_name}: {e}")
            raise
    
    def get_queue_length(self, queue_name: str) -> int:
        """
        Get approximate number of messages in queue.
        
        Args:
            queue_name: Queue to check
            
        Returns:
            Approximate message count
        """
        queue_client = self._get_queue_client(queue_name)
        
        try:
            properties = queue_client.get_queue_properties()
            count = properties.approximate_message_count
            logger.debug(f"📊 Queue {queue_name} has ~{count} messages")
            return count
            
        except Exception as e:
            logger.error(f"❌ Failed to get queue length for {queue_name}: {e}")
            return 0
    
    def clear_queue(self, queue_name: str) -> bool:
        """
        Clear all messages from queue.
        
        ⚠️ WARNING: This deletes ALL messages. Use with extreme caution.
        
        Args:
            queue_name: Queue to clear
            
        Returns:
            True if cleared successfully
        """
        queue_client = self._get_queue_client(queue_name)
        
        try:
            queue_client.clear_messages()
            logger.warning(f"🗑️ Cleared all messages from queue: {queue_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to clear queue {queue_name}: {e}")
            return False


# Factory function for dependency injection
def get_queue_repository() -> QueueRepository:
    """Get QueueRepository singleton instance"""
    return QueueRepository.instance()
```

### Factory Integration

```python
# repositories/factory.py (addition)

@staticmethod
def create_queue_repository() -> QueueRepository:
    """
    Create queue repository with authentication.
    
    This is THE centralized authentication point for all queue operations.
    Uses DefaultAzureCredential for seamless auth across environments.
    
    Returns:
        QueueRepository singleton instance
        
    Example:
        queue_repo = RepositoryFactory.create_queue_repository()
        queue_repo.send_message("jobs", job_message)
    """
    from repositories.queue import QueueRepository
    
    logger.info("🏭 Creating Queue repository")
    queue_repo = QueueRepository.instance()
    logger.info("✅ Queue repository created successfully")
    
    return queue_repo
```

---

## 🔄 Refactoring Controllers to Use QueueRepository

### Before (Anti-Pattern)
```python
# controller_base.py - WRONG
def send_job_to_queue(self, job_id: str, parameters: dict):
    # ❌ Creating credential in controller
    credential = DefaultAzureCredential()
    queue_service = QueueServiceClient(account_url, credential=credential)
    queue_client = queue_service.get_queue_client("geospatial-jobs")
    
    message_json = job_message.model_dump_json()
    queue_client.send_message(base64.b64encode(message_json.encode()).decode())
```

### After (Correct Pattern)
```python
# controller_base.py - CORRECT
def send_job_to_queue(self, job_id: str, parameters: dict):
    # ✅ Using repository pattern
    queue_repo = RepositoryFactory.create_queue_repository()
    
    job_message = JobQueueMessage(
        job_id=job_id,
        job_type=self.job_type,
        parameters=parameters,
        stage=1
    )
    
    message_id = queue_repo.send_message("geospatial-jobs", job_message)
    return {"job_id": job_id, "message_id": message_id}
```

---

## 📊 Singleton Usage Guidelines

### ✅ **GOOD Singleton Usage**

**Use singletons for:**
- External service clients (BlobServiceClient, QueueServiceClient)
- Database connection pools
- Authentication credentials (DefaultAzureCredential)
- Cache instances
- Configuration objects (after validation)

**Characteristics of good singletons:**
- Expensive to create
- Stateless or safely shareable state
- Benefits from connection pooling
- Thread-safe

### ❌ **BAD Singleton Usage**

**Don't use singletons for:**
- Registration/discovery (JobRegistry, TaskRegistry)
- Mutable business state
- Request-specific data
- Things that make testing difficult

**Problems with bad singletons:**
- Hidden global dependencies
- Testing nightmares
- Difficult to split into microservices
- Import-time side effects

---

## 🎯 Implementation Checklist

### Immediate Actions
- [ ] Create `repositories/queue.py` with QueueRepository
- [ ] Create `interfaces/repository.py` with IQueueRepository
- [ ] Update RepositoryFactory with `create_queue_repository()`
- [ ] Refactor all controllers to use QueueRepository
- [ ] Remove all DefaultAzureCredential from controllers
- [ ] Add unit tests for QueueRepository

### Validation Steps
1. **No credentials outside repositories**: `grep -r "DefaultAzureCredential" --include="*.py" | grep -v repositories/`
2. **All queue operations via repository**: `grep -r "QueueServiceClient" --include="*.py" | grep -v repositories/`
3. **Singleton reuse**: Monitor logs for "Initializing QueueRepository" - should appear once per worker

---

## 🏆 Benefits After Implementation

1. **Performance**: DefaultAzureCredential created once, not 100s of times
2. **Clean Architecture**: Controllers don't know about Azure infrastructure
3. **Testability**: Mock one repository interface, not Azure SDKs
4. **Consistency**: All repositories follow same pattern
5. **Maintainability**: Queue logic centralized in one place
6. **Monitoring**: Single point to add metrics/logging for all queue operations

---

## 📚 Summary

The Queue Repository completes your repository pattern implementation:

| Resource | Repository | Singleton | Status |
|----------|------------|-----------|---------|
| Blob Storage | BlobRepository | ✅ | Implemented |
| Database | Job/TaskRepository | ✅ | Implemented |
| Queues | QueueRepository | ✅ | **To Implement** |
| Key Vault | VaultRepository | ✅ | Future |

Remember: **Repositories own credentials, Controllers own orchestration, Services own business logic.**

---

*This pattern ensures clean separation of concerns and efficient resource usage in your Azure Functions architecture.*