"""
Diagnostic endpoint to check state management in Azure
Add this to function_app.py temporarily for debugging
"""
import azure.functions as func
import json
import logging
from state_integration import StateIntegration
from state_models import TaskMessage, TaskType
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

def diagnose_state_management(req: func.HttpRequest) -> func.HttpResponse:
    """
    Diagnostic endpoint to test state management components
    """
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'checks': []
    }
    
    # Test 1: Can StateIntegration initialize?
    try:
        state_integration = StateIntegration()
        results['checks'].append({
            'test': 'StateIntegration initialization',
            'status': 'success',
            'state_manager': state_integration.state_manager is not None,
            'task_router': state_integration.task_router is not None
        })
    except Exception as e:
        results['checks'].append({
            'test': 'StateIntegration initialization',
            'status': 'failed',
            'error': str(e)
        })
        return func.HttpResponse(
            json.dumps(results, indent=2),
            status_code=200,
            mimetype="application/json"
        )
    
    # Test 2: Can we create a test task message?
    try:
        task_message = TaskMessage(
            task_id=str(uuid.uuid4()),
            job_id="test_job_diag",
            task_type=TaskType.CREATE_COG.value,
            sequence_number=1,
            parameters={'test': 'params'}
        )
        task_dict = task_message.to_dict()
        results['checks'].append({
            'test': 'TaskMessage creation',
            'status': 'success',
            'task_id': task_message.task_id,
            'task_type': task_message.task_type
        })
    except Exception as e:
        results['checks'].append({
            'test': 'TaskMessage creation',
            'status': 'failed',
            'error': str(e)
        })
    
    # Test 3: Can we route a task?
    if state_integration.task_router:
        try:
            # Don't actually execute, just check if routing works
            handlers = state_integration.task_router.handlers
            results['checks'].append({
                'test': 'TaskRouter handlers',
                'status': 'success',
                'handlers': list(handlers.keys())
            })
        except Exception as e:
            results['checks'].append({
                'test': 'TaskRouter handlers',
                'status': 'failed',
                'error': str(e)
            })
    
    # Test 4: Check environment variables
    from config import Config
    results['checks'].append({
        'test': 'Environment configuration',
        'status': 'success',
        'storage_account': Config.STORAGE_ACCOUNT_NAME,
        'has_connection_string': Config.AZURE_WEBJOBS_STORAGE is not None,
        'silver_container': Config.SILVER_CONTAINER_NAME,
        'silver_temp_folder': Config.SILVER_TEMP_FOLDER,
        'silver_cogs_folder': Config.SILVER_COGS_FOLDER
    })
    
    # Test 5: Can we access storage?
    if state_integration.state_manager:
        try:
            # Try to get a non-existent job (should not error)
            job = state_integration.state_manager.get_job("nonexistent")
            results['checks'].append({
                'test': 'StateManager storage access',
                'status': 'success',
                'can_access_tables': True
            })
        except Exception as e:
            results['checks'].append({
                'test': 'StateManager storage access',
                'status': 'failed',
                'error': str(e)
            })
    
    # Summary
    all_passed = all(check['status'] == 'success' for check in results['checks'])
    results['summary'] = {
        'all_tests_passed': all_passed,
        'total_checks': len(results['checks']),
        'passed': sum(1 for c in results['checks'] if c['status'] == 'success'),
        'failed': sum(1 for c in results['checks'] if c['status'] == 'failed')
    }
    
    return func.HttpResponse(
        json.dumps(results, indent=2),
        status_code=200,
        mimetype="application/json"
    )