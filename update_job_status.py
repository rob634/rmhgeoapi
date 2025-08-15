#!/usr/bin/env python3
"""
Script to update job status in Azure Storage table
Marks hello_world jobs as completed
"""
import os
from repositories import JobRepository
from models import JobStatus
from config import Config

def update_hello_world_jobs():
    """Update all hello_world jobs to completed status"""
    
    # Set environment variables for storage account
    # You may need to set STORAGE_ACCOUNT_NAME if using managed identity
    # or AzureWebJobsStorage connection string for local development
    
    print("Updating hello_world jobs to completed status...")
    print(f"Storage account: {Config.STORAGE_ACCOUNT_NAME}")
    
    try:
        job_repo = JobRepository()
        
        # Specific job ID from your table
        job_id = "56a1b50acddd1539346544d65441d98c2a0276a3a4204058a24bb7983ba6afaf"
        
        # Check current status
        current_status = job_repo.get_job_status(job_id)
        if current_status:
            print(f"Current status: {current_status.status}")
            
            if current_status.status in [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.PROCESSING]:
                # Update to completed with mock result
                result_data = {
                    "message": "Hello World task completed successfully",
                    "processed_at": "2025-08-15T02:45:00Z",
                    "operation": "hello_world",
                    "status": "success"
                }
                
                job_repo.update_job_status(
                    job_id, 
                    JobStatus.COMPLETED,
                    result_data=result_data
                )
                
                print(f"✅ Updated job {job_id} to COMPLETED")
            else:
                print(f"Job {job_id} is already in status: {current_status.status}")
        else:
            print(f"❌ Job {job_id} not found")
            
    except Exception as e:
        print(f"❌ Error updating job status: {e}")
        raise

if __name__ == "__main__":
    # You may need to set these environment variables before running:
    # export STORAGE_ACCOUNT_NAME="your-storage-account"
    # or
    # export AzureWebJobsStorage="your-connection-string"
    
    update_hello_world_jobs()