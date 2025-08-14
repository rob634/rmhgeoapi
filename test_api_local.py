#!/usr/bin/env python3
"""
Local API test script for Azure Functions geospatial ETL pipeline
Tests the submit_job and get_job_status endpoints
"""
import requests
import json
import time
import sys
from typing import Dict, Any

# API Base URL
BASE_URL = "http://localhost:7071/api"

def submit_job(dataset_id: str, resource_id: str, version_id: str, operation_type: str) -> Dict[str, Any]:
    """Submit a new job to the API"""
    url = f"{BASE_URL}/jobs"
    
    payload = {
        "dataset_id": dataset_id,
        "resource_id": resource_id,
        "version_id": version_id,
        "operation_type": operation_type
    }
    
    print(f"🚀 Submitting job...")
    print(f"   URL: {url}")
    print(f"   Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Success: {json.dumps(result, indent=2)}")
            return result
        else:
            print(f"   ❌ Error: {response.text}")
            return {"error": response.text, "status_code": response.status_code}
            
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request failed: {str(e)}")
        return {"error": str(e)}

def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get job status by job ID"""
    url = f"{BASE_URL}/jobs/{job_id}"
    
    print(f"📊 Getting job status...")
    print(f"   URL: {url}")
    
    try:
        response = requests.get(url, timeout=30)
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Success: {json.dumps(result, indent=2)}")
            return result
        elif response.status_code == 404:
            print(f"   ❌ Job not found: {job_id}")
            return {"error": "Job not found", "status_code": 404}
        else:
            print(f"   ❌ Error: {response.text}")
            return {"error": response.text, "status_code": response.status_code}
            
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request failed: {str(e)}")
        return {"error": str(e)}

def test_complete_workflow():
    """Test the complete job submission and tracking workflow"""
    print("=" * 60)
    print("🧪 TESTING COMPLETE WORKFLOW")
    print("=" * 60)
    
    # Test job submission
    job_response = submit_job(
        dataset_id="test-dataset-001",
        resource_id="resource-456",
        version_id="v1.0.0",
        operation_type="cog_conversion"
    )
    
    if "error" in job_response:
        print("❌ Job submission failed, stopping test")
        return
    
    job_id = job_response.get("job_id")
    if not job_id:
        print("❌ No job_id returned, stopping test")
        return
    
    print(f"\n📝 Job ID: {job_id}")
    
    # Check job status immediately
    print("\n" + "-" * 40)
    get_job_status(job_id)
    
    # Wait a bit and check again (in case queue processing happens)
    print("\n" + "-" * 40)
    print("⏳ Waiting 3 seconds...")
    time.sleep(3)
    get_job_status(job_id)
    
    # Test idempotency - submit same job again
    print("\n" + "-" * 40)
    print("🔁 Testing idempotency (submitting same job again)...")
    duplicate_response = submit_job(
        dataset_id="test-dataset-001",
        resource_id="resource-456", 
        version_id="v1.0.0",
        operation_type="cog_conversion"
    )
    
    # Test different job
    print("\n" + "-" * 40)
    print("📝 Submitting different job...")
    different_job = submit_job(
        dataset_id="test-dataset-002",
        resource_id="resource-789",
        version_id="v2.1.0", 
        operation_type="vector_upload"
    )

def test_error_cases():
    """Test various error scenarios"""
    print("\n" + "=" * 60)
    print("🧪 TESTING ERROR CASES")
    print("=" * 60)
    
    # Test missing required fields
    print("🚫 Testing missing dataset_id...")
    try:
        response = requests.post(f"{BASE_URL}/jobs", json={
            "resource_id": "test-resource",
            "version_id": "v1.0",
            "operation_type": "test"
        }, timeout=10)
        print(f"   Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request failed: {str(e)}")
    
    # Test invalid JSON
    print("\n🚫 Testing invalid JSON...")
    try:
        response = requests.post(f"{BASE_URL}/jobs", data="invalid json", timeout=10)
        print(f"   Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request failed: {str(e)}")
    
    # Test non-existent job ID
    print("\n🚫 Testing non-existent job...")
    get_job_status("non-existent-job-id-12345")

def test_various_operations():
    """Test different operation types"""
    print("\n" + "=" * 60)
    print("🧪 TESTING VARIOUS OPERATIONS")
    print("=" * 60)
    
    operations = [
        "cog_conversion",
        "vector_upload", 
        "stac_generation",
        "hello_world"
    ]
    
    for i, operation in enumerate(operations, 1):
        print(f"\n📝 Test {i}: {operation}")
        submit_job(
            dataset_id=f"dataset-{operation}",
            resource_id=f"resource-{i:03d}",
            version_id=f"v{i}.0.0",
            operation_type=operation
        )

def check_functions_running():
    """Check if Azure Functions are running"""
    try:
        response = requests.get(f"{BASE_URL.replace('/api', '')}/admin/host/status", timeout=5)
        return True
    except requests.exceptions.RequestException:
        return False

def main():
    """Main test runner"""
    print("🔍 Checking if Azure Functions are running...")
    if not check_functions_running():
        print("❌ Azure Functions not running!")
        print("\n📋 To start Azure Functions:")
        print("   1. Open a terminal in this directory")
        print("   2. Run: func start")
        print("   3. Wait for 'Host started' message")
        print("   4. Then run this test script")
        print(f"\n🌐 Expected URL: {BASE_URL}")
        return
    
    print("✅ Azure Functions are running!")
    print("")
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "submit":
            # Quick submit test
            submit_job("quick-test", "resource-001", "v1.0", "hello_world")
            
        elif command == "status" and len(sys.argv) > 2:
            # Quick status check
            job_id = sys.argv[2]
            get_job_status(job_id)
            
        elif command == "errors":
            # Test error cases only
            test_error_cases()
            
        elif command == "operations":
            # Test different operations
            test_various_operations()
            
        else:
            print("Usage:")
            print("  python test_api_local.py                    # Run full test suite")
            print("  python test_api_local.py submit             # Quick submit test")
            print("  python test_api_local.py status <job_id>    # Check job status")
            print("  python test_api_local.py errors             # Test error cases")
            print("  python test_api_local.py operations         # Test different operations")
            
    else:
        # Run full test suite
        test_complete_workflow()
        test_error_cases()
        test_various_operations()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED")
        print("=" * 60)

if __name__ == "__main__":
    main()