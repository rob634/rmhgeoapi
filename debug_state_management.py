#!/usr/bin/env python3
"""
Debug toolkit for state management system
Helps identify why tasks get stuck in PROCESSING state
"""
import json
import base64
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

from azure.storage.queue import QueueServiceClient
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

from config import Config
from state_models import JobState, TaskState, TaskMessage
from logger_setup import get_logger

logger = get_logger(__name__)


class StateDebugger:
    """Debug utilities for state management system"""
    
    def __init__(self):
        """Initialize Azure clients"""
        if Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity
            credential = DefaultAzureCredential()
            queue_url = Config.get_storage_account_url('queue')
            table_url = Config.get_storage_account_url('table')
            blob_url = Config.get_storage_account_url('blob')
            
            self.queue_service = QueueServiceClient(queue_url, credential=credential)
            self.table_service = TableServiceClient(table_url, credential=credential)
            self.blob_service = BlobServiceClient(blob_url, credential=credential)
        else:
            # Use connection string
            conn_str = Config.AZURE_WEBJOBS_STORAGE
            self.queue_service = QueueServiceClient.from_connection_string(conn_str)
            self.table_service = TableServiceClient.from_connection_string(conn_str)
            self.blob_service = BlobServiceClient.from_connection_string(conn_str)
    
    def check_job_state(self, job_id: str) -> Dict[str, Any]:
        """Check complete state of a job"""
        result = {
            'job_id': job_id,
            'job_record': None,
            'tasks': [],
            'queue_messages': [],
            'poison_messages': [],
            'errors': []
        }
        
        try:
            # Get job from Table Storage
            job_table = self.table_service.get_table_client('jobs')
            try:
                job_entity = job_table.get_entity(partition_key='job', row_key=job_id)
                result['job_record'] = {
                    'status': job_entity.get('status'),
                    'operation_type': job_entity.get('operation_type'),
                    'created_at': job_entity.get('created_at'),
                    'updated_at': job_entity.get('updated_at'),
                    'error_message': job_entity.get('error_message'),
                    'total_tasks': job_entity.get('total_tasks'),
                    'completed_tasks': job_entity.get('completed_tasks'),
                    'failed_tasks': job_entity.get('failed_tasks')
                }
            except Exception as e:
                result['errors'].append(f"Job not found in table: {e}")
            
            # Get tasks from Table Storage
            task_table = self.table_service.get_table_client('tasks')
            try:
                tasks = task_table.query_entities(
                    filter=f"PartitionKey eq '{job_id}'"
                )
                for task in tasks:
                    result['tasks'].append({
                        'task_id': task.get('RowKey'),
                        'status': task.get('status'),
                        'task_type': task.get('task_type'),
                        'sequence_number': task.get('sequence_number'),
                        'created_at': task.get('created_at'),
                        'updated_at': task.get('updated_at'),
                        'error_message': task.get('error_message')
                    })
            except Exception as e:
                result['errors'].append(f"Error fetching tasks: {e}")
            
            # Check geospatial-tasks queue for related messages
            tasks_queue = self.queue_service.get_queue_client('geospatial-tasks')
            try:
                messages = tasks_queue.peek_messages(max_messages=32)
                for msg in messages:
                    try:
                        # Decode message
                        decoded = base64.b64decode(msg.content).decode('utf-8')
                        msg_data = json.loads(decoded)
                        if msg_data.get('job_id') == job_id:
                            result['queue_messages'].append({
                                'task_id': msg_data.get('task_id'),
                                'task_type': msg_data.get('task_type'),
                                'dequeue_count': msg.dequeue_count
                            })
                    except Exception as e:
                        pass
            except Exception as e:
                result['errors'].append(f"Error checking task queue: {e}")
            
            # Check poison queue
            poison_queue = self.queue_service.get_queue_client('geospatial-tasks-poison')
            try:
                messages = poison_queue.peek_messages(max_messages=32)
                for msg in messages:
                    try:
                        decoded = base64.b64decode(msg.content).decode('utf-8')
                        msg_data = json.loads(decoded)
                        if msg_data.get('job_id') == job_id:
                            result['poison_messages'].append({
                                'task_id': msg_data.get('task_id'),
                                'task_type': msg_data.get('task_type')
                            })
                    except Exception as e:
                        pass
            except Exception as e:
                result['errors'].append(f"Error checking poison queue: {e}")
            
        except Exception as e:
            result['errors'].append(f"General error: {e}")
        
        return result
    
    def trace_task_execution(self, task_id: str, job_id: str) -> Dict[str, Any]:
        """Trace what happened to a specific task"""
        result = {
            'task_id': task_id,
            'job_id': job_id,
            'task_record': None,
            'in_queue': False,
            'in_poison': False,
            'execution_logs': [],
            'errors': []
        }
        
        try:
            # Get task record
            task_table = self.table_service.get_table_client('tasks')
            try:
                task_entity = task_table.get_entity(
                    partition_key=job_id,
                    row_key=task_id
                )
                result['task_record'] = {
                    'status': task_entity.get('status'),
                    'task_type': task_entity.get('task_type'),
                    'created_at': task_entity.get('created_at'),
                    'updated_at': task_entity.get('updated_at'),
                    'error_message': task_entity.get('error_message'),
                    'duration_seconds': task_entity.get('duration_seconds')
                }
            except Exception as e:
                result['errors'].append(f"Task not found: {e}")
            
            # Check if task is still in queue
            tasks_queue = self.queue_service.get_queue_client('geospatial-tasks')
            messages = tasks_queue.peek_messages(max_messages=32)
            for msg in messages:
                try:
                    decoded = base64.b64decode(msg.content).decode('utf-8')
                    msg_data = json.loads(decoded)
                    if msg_data.get('task_id') == task_id:
                        result['in_queue'] = True
                        result['execution_logs'].append(f"Task found in queue with dequeue_count={msg.dequeue_count}")
                except:
                    pass
            
            # Check poison queue
            poison_queue = self.queue_service.get_queue_client('geospatial-tasks-poison')
            messages = poison_queue.peek_messages(max_messages=32)
            for msg in messages:
                try:
                    decoded = base64.b64decode(msg.content).decode('utf-8')
                    msg_data = json.loads(decoded)
                    if msg_data.get('task_id') == task_id:
                        result['in_poison'] = True
                        result['execution_logs'].append("Task found in poison queue - failed 5+ times")
                except:
                    pass
            
        except Exception as e:
            result['errors'].append(f"Error tracing task: {e}")
        
        return result
    
    def inject_test_task(self, job_id: str) -> str:
        """Inject a test task directly into the queue to test processing"""
        import uuid
        
        task_id = str(uuid.uuid4())
        
        # Create a simple test task
        task_message = TaskMessage(
            task_id=task_id,
            job_id=job_id,
            task_type='CREATE_COG',
            sequence_number=99,  # High number to not conflict
            parameters={
                'dataset_id': 'rmhazuregeobronze',
                'resource_id': 'test_file.tif',
                'version_id': 'debug_test',
                'input_path': 'rmhazuregeobronze/test_file.tif',
                'output_path': f'rmhazuregeosilver/temp/{job_id}/test_output.tif'
            }
        )
        
        # Queue the message
        tasks_queue = self.queue_service.get_queue_client('geospatial-tasks')
        message_json = json.dumps(task_message.to_dict())
        message_bytes = message_json.encode('utf-8')
        message_b64 = base64.b64encode(message_bytes).decode('utf-8')
        
        tasks_queue.send_message(message_b64)
        
        logger.info(f"Injected test task {task_id} for job {job_id}")
        return task_id
    
    def check_queue_health(self) -> Dict[str, Any]:
        """Check health of all queues"""
        result = {
            'queues': {},
            'issues': []
        }
        
        queue_names = [
            'geospatial-jobs',
            'geospatial-tasks', 
            'geospatial-jobs-poison',
            'geospatial-tasks-poison'
        ]
        
        for queue_name in queue_names:
            try:
                queue_client = self.queue_service.get_queue_client(queue_name)
                properties = queue_client.get_queue_properties()
                
                result['queues'][queue_name] = {
                    'exists': True,
                    'approximate_message_count': properties.approximate_message_count
                }
                
                # Peek at messages if any
                if properties.approximate_message_count > 0:
                    messages = queue_client.peek_messages(max_messages=1)
                    if messages:
                        msg = messages[0]
                        try:
                            decoded = base64.b64decode(msg.content).decode('utf-8')
                            msg_data = json.loads(decoded)
                            result['queues'][queue_name]['sample_message'] = {
                                'job_id': msg_data.get('job_id', 'N/A')[:16] + '...',
                                'task_type': msg_data.get('task_type', msg_data.get('operation_type', 'N/A'))
                            }
                        except:
                            result['queues'][queue_name]['sample_message'] = 'Could not decode'
                
            except Exception as e:
                result['queues'][queue_name] = {
                    'exists': False,
                    'error': str(e)
                }
                result['issues'].append(f"Queue {queue_name}: {e}")
        
        return result
    
    def analyze_stuck_job(self, job_id: str) -> None:
        """Comprehensive analysis of a stuck job"""
        print(f"\n{'='*60}")
        print(f"ANALYZING STUCK JOB: {job_id[:16]}...")
        print(f"{'='*60}\n")
        
        # Check job state
        job_state = self.check_job_state(job_id)
        
        print("📊 JOB RECORD:")
        if job_state['job_record']:
            for key, value in job_state['job_record'].items():
                print(f"  {key}: {value}")
        else:
            print("  ❌ Job not found in table storage")
        
        print(f"\n📋 TASKS ({len(job_state['tasks'])} total):")
        for task in job_state['tasks']:
            status_icon = "✅" if task['status'] == 'COMPLETED' else "❌" if task['status'] == 'FAILED' else "⏳"
            print(f"  {status_icon} {task['task_type']} - {task['status']}")
            print(f"     Task ID: {task['task_id'][:16]}...")
            if task.get('error_message'):
                print(f"     Error: {task['error_message'][:100]}...")
        
        print(f"\n📬 QUEUE MESSAGES ({len(job_state['queue_messages'])} in queue):")
        for msg in job_state['queue_messages']:
            print(f"  - {msg['task_type']} (dequeue_count: {msg['dequeue_count']})")
        
        print(f"\n☠️ POISON MESSAGES ({len(job_state['poison_messages'])} in poison):")
        for msg in job_state['poison_messages']:
            print(f"  - {msg['task_type']}")
        
        if job_state['errors']:
            print(f"\n⚠️ ERRORS DURING ANALYSIS:")
            for error in job_state['errors']:
                print(f"  - {error}")
        
        # Trace each task
        print(f"\n🔍 DETAILED TASK TRACES:")
        for task in job_state['tasks']:
            if task['status'] in ['PROCESSING', 'FAILED']:
                trace = self.trace_task_execution(task['task_id'], job_id)
                print(f"\n  Task {task['task_id'][:16]}... ({task['task_type']}):")
                print(f"    Status: {trace['task_record']['status'] if trace['task_record'] else 'Unknown'}")
                print(f"    In Queue: {trace['in_queue']}")
                print(f"    In Poison: {trace['in_poison']}")
                for log in trace['execution_logs']:
                    print(f"    - {log}")
        
        # Check queue health
        print(f"\n🏥 QUEUE HEALTH CHECK:")
        queue_health = self.check_queue_health()
        for queue_name, info in queue_health['queues'].items():
            if info['exists']:
                print(f"  {queue_name}: {info['approximate_message_count']} messages")
                if 'sample_message' in info:
                    print(f"    Sample: {info['sample_message']}")
            else:
                print(f"  {queue_name}: ❌ Not accessible")
        
        print(f"\n{'='*60}\n")


def main():
    """Main debug function"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python debug_state_management.py <job_id>")
        print("\nExample:")
        print("  python debug_state_management.py 07c5bdad8a7cb9b9...")
        sys.exit(1)
    
    job_id = sys.argv[1]
    
    # If short ID provided, show warning
    if len(job_id) < 64:
        print(f"⚠️ Warning: Job ID appears truncated. Full 64-char ID recommended.")
    
    debugger = StateDebugger()
    debugger.analyze_stuck_job(job_id)
    
    # Optional: inject test task
    if len(sys.argv) > 2 and sys.argv[2] == '--inject-test':
        print("\n💉 Injecting test task...")
        task_id = debugger.inject_test_task(job_id)
        print(f"Test task injected: {task_id}")


if __name__ == "__main__":
    main()