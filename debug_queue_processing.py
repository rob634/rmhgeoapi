#!/usr/bin/env python3
"""
Debug script to test queue processing functionality locally.

This script simulates the queue trigger processing to identify 
where the failure is occurring that causes messages to go to poison queue.
"""

import json
import sys

from util_logger import LoggerFactory, ComponentType

# Set up logging using LoggerFactory
logger = LoggerFactory.get_logger(ComponentType.UTIL, "QueueDebugger")

def test_basic_imports():
    """Test all imports that the queue trigger uses"""
    logger.info("Testing basic imports...")
    
    try:
        from schema_core import JobStatus, TaskStatus, JobQueueMessage, TaskQueueMessage
        logger.info("✅ Core schema imports successful")
    except Exception as e:
        logger.error(f"❌ Failed to import from schema_core: {e}")
        return False
    
    try:
        from repository_data import RepositoryFactory
        logger.info("✅ RepositoryFactory import successful")
    except Exception as e:
        logger.error(f"❌ Failed to import RepositoryFactory: {e}")
        return False
    
    try:
        from controller_hello_world import HelloWorldController
        logger.info("✅ HelloWorldController import successful")
    except Exception as e:
        logger.error(f"❌ Failed to import HelloWorldController: {e}")
        return False
    
    return True

def test_message_validation():
    """Test JobQueueMessage validation"""
    logger.info("Testing JobQueueMessage validation...")
    
    try:
        from schema_core import JobQueueMessage
        
        # Create a test message similar to what would be sent
        test_message = {
            "job_id": "1da528345c54f2ee0bfda24dcd52228a686390bf1ecd6b6c6c3a63cc007f127e",
            "job_type": "hello_world",
            "stage": 1,
            "parameters": {"n": 3, "message": "Hello World!"},
            "stage_results": {},
            "retry_count": 0
        }
        
        message_json = json.dumps(test_message)
        logger.info(f"Test message JSON: {message_json}")
        
        # Try to validate it
        job_message = JobQueueMessage.model_validate_json(message_json)
        logger.info(f"✅ Message validation successful: {job_message}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Message validation failed: {e}")
        return False

def test_repository_creation():
    """Test repository creation"""
    logger.info("Testing repository creation...")
    
    try:
        from repository_data import RepositoryFactory
        job_repo, task_repo, completion_detector = RepositoryFactory.create_repositories('postgres')
        logger.info(f"✅ Repositories created successfully")
        logger.info(f"   job_repo: {type(job_repo)}")
        logger.info(f"   task_repo: {type(task_repo)}")
        logger.info(f"   completion_detector: {type(completion_detector)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Repository creation failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def test_controller_instantiation():
    """Test controller instantiation"""
    logger.info("Testing HelloWorldController instantiation...")
    
    try:
        from controller_hello_world import HelloWorldController
        controller = HelloWorldController()
        logger.info(f"✅ Controller instantiated successfully: {type(controller)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Controller instantiation failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def main():
    """Run all diagnostic tests"""
    logger.info("🔍 Starting queue processing diagnostics...")
    
    tests = [
        ("Basic Imports", test_basic_imports),
        ("Message Validation", test_message_validation),
        ("Repository Creation", test_repository_creation),
        ("Controller Instantiation", test_controller_instantiation)
    ]
    
    results = {}
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            import traceback
            logger.error(f"Crash traceback: {traceback.format_exc()}")
            results[test_name] = False
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info(f"{'='*50}")
    
    all_passed = True
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        logger.info("\n🎉 All tests passed! The issue might be environment-specific.")
        logger.info("   Possible causes:")
        logger.info("   - Azure Functions runtime environment differences")
        logger.info("   - Environment variables not set in Azure")
        logger.info("   - Database connection issues in Azure")
        logger.info("   - Managed identity authentication issues")
    else:
        logger.info("\n🚨 Some tests failed! This likely explains the poison queue messages.")
        logger.info("   Fix the failing imports/components above.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())