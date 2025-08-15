#!/usr/bin/env python3
"""
Manually process pending hello_world jobs
"""
import os
from repositories import JobRepository
from services import ServiceFactory
from models import JobStatus

def manually_process_pending_jobs():
    """Find and manually process pending hello_world jobs"""
    
    print("Manually processing pending hello_world jobs...")
    
    try:
        job_repo = JobRepository()
        
        # Specific job ID that's stuck in pending
        job_id = "56a1b50acddd1539346544d65441d98c2a0276a3a4204058a24bb7983ba6afaf"
        
        # Get job details
        job_details = job_repo.get_job_details(job_id)
        if not job_details:
            print(f"❌ Job {job_id} not found")
            return
            
        print(f"📋 Found job: {job_id}")
        print(f"📊 Current status: {job_details['status']}")
        print(f"⚙️  Operation: {job_details['operation_type']}")
        
        if job_details['status'] == JobStatus.PENDING:
            print("🚀 Processing job manually...")
            
            # Update status to processing
            job_repo.update_job_status(job_id, JobStatus.PROCESSING)
            print("📈 Status updated to PROCESSING")
            
            # Get service and process
            service = ServiceFactory.get_service(job_details['operation_type'])
            result = service.process(
                job_id=job_id,
                dataset_id=job_details['dataset_id'],
                resource_id=job_details['resource_id'], 
                version_id=job_details['version_id'],
                operation_type=job_details['operation_type']
            )
            
            # Update status to completed
            job_repo.update_job_status(job_id, JobStatus.COMPLETED, result_data=result)
            print("✅ Status updated to COMPLETED")
            print(f"🎯 Result: {result}")
            
        else:
            print(f"ℹ️  Job is not pending (status: {job_details['status']})")
            
    except Exception as e:
        print(f"❌ Error processing job: {e}")
        raise

if __name__ == "__main__":
    # Set your storage account name
    os.environ['STORAGE_ACCOUNT_NAME'] = 'rmhgeostorageaccdj8js'
    manually_process_pending_jobs()