#!/usr/bin/env python3
"""
Query Azure Table Storage directly to inspect job statuses
Helps debug why jobs remain in queued status
"""
import os
import json
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient
from config import Config


def load_local_settings():
    """Load settings from local.settings.json for standalone scripts"""
    try:
        with open('local.settings.json', 'r') as f:
            settings = json.load(f)
            values = settings.get('Values', {})
            
            # Set environment variables
            for key, value in values.items():
                os.environ[key] = value
            
            # Reload the Config class to pick up new environment variables
            import importlib
            import config
            importlib.reload(config)
            
            print(f"✅ Loaded {len(values)} settings from local.settings.json")
            return True
    except Exception as e:
        print(f"⚠️ Could not load local.settings.json: {e}")
        return False


def query_jobs_table():
    """Query the jobs table directly from Table Storage"""
    print("🔍 Querying Jobs Table Storage Directly")
    print("=" * 60)
    
    try:
        # Initialize Table Storage client (same logic as repositories)
        print(f"🔍 Checking config - AZURE_WEBJOBS_STORAGE: {'Yes' if Config.AZURE_WEBJOBS_STORAGE else 'No'}")
        print(f"🔍 Checking config - STORAGE_ACCOUNT_NAME: {Config.STORAGE_ACCOUNT_NAME}")
        
        if Config.AZURE_WEBJOBS_STORAGE:
            # Use connection string for local development
            table_service = TableServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
            print("✅ Using connection string for local development")
        elif Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity in production
            from azure.identity import DefaultAzureCredential
            account_url = Config.get_storage_account_url('table')
            table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
            print("✅ Using managed identity for production")
        else:
            print("❌ No storage configuration found")
            print(f"   AZURE_WEBJOBS_STORAGE: {Config.AZURE_WEBJOBS_STORAGE}")
            print(f"   STORAGE_ACCOUNT_NAME: {Config.STORAGE_ACCOUNT_NAME}")
            return False
        
        table_name = "jobs"
        
        # Check if table exists
        try:
            table_client = table_service.get_table_client(table_name)
            print(f"✅ Connected to table: {table_name}")
        except Exception as e:
            print(f"❌ Error connecting to table: {e}")
            return False
        
        # Query all jobs
        print(f"\n📊 Querying all jobs from table...")
        entities = list(table_client.query_entities("PartitionKey eq 'jobs'"))
        
        if not entities:
            print("📭 No jobs found in table")
            return True
        
        print(f"📋 Found {len(entities)} jobs in table")
        print("=" * 60)
        
        # Group jobs by status
        status_counts = {}
        jobs_by_status = {}
        
        for entity in entities:
            status = entity.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            
            if status not in jobs_by_status:
                jobs_by_status[status] = []
            jobs_by_status[status].append(entity)
        
        # Show status summary
        print("📈 Job Status Summary:")
        for status, count in status_counts.items():
            print(f"   {status}: {count} jobs")
        
        # Show detailed job information
        for status, jobs in jobs_by_status.items():
            print(f"\n📋 {status.upper()} JOBS ({len(jobs)}):")
            print("-" * 40)
            
            for job in jobs[:5]:  # Show first 5 jobs of each status
                job_id = job.get('RowKey', 'unknown')[:16] + "..."
                dataset_id = job.get('dataset_id', 'N/A')
                operation_type = job.get('operation_type', 'N/A')
                created_at = job.get('created_at', 'N/A')
                updated_at = job.get('updated_at', 'N/A')
                system = job.get('system', False)
                
                print(f"   🆔 Job: {job_id}")
                print(f"   📊 Dataset: {dataset_id}")
                print(f"   🔧 Operation: {operation_type}")
                print(f"   🏷️ System: {system}")
                print(f"   📅 Created: {created_at}")
                print(f"   🔄 Updated: {updated_at}")
                
                # Check for request parameters
                if 'request_parameters' in job:
                    print(f"   📋 Has request_parameters: Yes")
                else:
                    print(f"   📋 Has request_parameters: No")
                
                # Check time difference
                if created_at != 'N/A' and updated_at != 'N/A':
                    try:
                        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        time_diff = updated - created
                        print(f"   ⏱️ Processing time: {time_diff.total_seconds():.1f} seconds")
                    except:
                        print(f"   ⏱️ Processing time: Unable to calculate")
                
                print()
            
            if len(jobs) > 5:
                print(f"   ... and {len(jobs) - 5} more {status} jobs")
        
        # Check for stuck jobs
        print("\n🔍 Analyzing Stuck Jobs:")
        current_time = datetime.now(timezone.utc)
        stuck_jobs = []
        
        for entity in entities:
            status = entity.get('status')
            created_at = entity.get('created_at')
            
            if status in ['queued', 'processing'] and created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    age_minutes = (current_time - created).total_seconds() / 60
                    
                    if age_minutes > 5:  # Jobs older than 5 minutes
                        stuck_jobs.append({
                            'job_id': entity.get('RowKey', 'unknown')[:16] + "...",
                            'status': status,
                            'age_minutes': age_minutes,
                            'operation': entity.get('operation_type', 'N/A')
                        })
                except:
                    pass
        
        if stuck_jobs:
            print(f"⚠️ Found {len(stuck_jobs)} potentially stuck jobs:")
            for job in stuck_jobs[:10]:  # Show first 10 stuck jobs
                print(f"   🆔 {job['job_id']} - {job['status']} for {job['age_minutes']:.1f} minutes ({job['operation']})")
        else:
            print("✅ No stuck jobs found")
        
        return True
        
    except Exception as e:
        print(f"❌ Error querying jobs table: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_queue_status():
    """Check the Azure Storage Queue status"""
    print(f"\n📬 Checking Azure Storage Queue Status")
    print("=" * 60)
    
    try:
        from azure.storage.queue import QueueServiceClient
        
        # Initialize queue client (same logic as function_app)
        if Config.AZURE_WEBJOBS_STORAGE:
            queue_service = QueueServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
        elif Config.STORAGE_ACCOUNT_NAME:
            from azure.identity import DefaultAzureCredential
            account_url = Config.get_storage_account_url('queue')
            queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            print("❌ No storage configuration found")
            return False
        
        queue_name = "job-processing"
        queue_client = queue_service.get_queue_client(queue_name)
        
        # Get queue properties
        properties = queue_client.get_queue_properties()
        message_count = properties.approximate_message_count
        
        print(f"📬 Queue: {queue_name}")
        print(f"📊 Approximate message count: {message_count}")
        
        if message_count > 0:
            print("⚠️ Messages are waiting in queue but not being processed")
            print("💡 This suggests the Azure Functions queue trigger may not be working")
        else:
            print("✅ Queue is empty - messages are being processed or not being added")
        
        # Try to peek at messages (non-destructive)
        try:
            messages = queue_client.peek_messages(max_messages=5)
            if messages:
                print(f"\n📄 Sample queue messages:")
                for i, msg in enumerate(messages, 1):
                    print(f"   {i}. Message ID: {msg.id}")
                    print(f"      Content: {msg.content[:100]}...")
                    print(f"      Insertion time: {msg.insertion_time}")
                    print()
        except Exception as e:
            print(f"❌ Could not peek at queue messages: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking queue: {e}")
        return False


def suggest_fixes():
    """Suggest potential fixes for stuck jobs"""
    print(f"\n🔧 Potential Solutions for Stuck Jobs")
    print("=" * 60)
    
    solutions = [
        {
            "issue": "Jobs stuck in 'queued' status",
            "causes": [
                "Azure Functions queue trigger not working",
                "Queue messages not being processed", 
                "Function app not running or crashed",
                "Local development vs production configuration"
            ],
            "solutions": [
                "Restart the Azure Functions app",
                "Check function app logs for errors",
                "Verify queue trigger is properly configured", 
                "Manually process jobs using the /process endpoint",
                "Check if the function app is running in production"
            ]
        },
        {
            "issue": "Jobs stuck in 'processing' status",
            "causes": [
                "Function execution timeout",
                "Unhandled exceptions in processing",
                "Service dependencies not available"
            ],
            "solutions": [
                "Check function app logs for errors",
                "Increase function timeout if needed",
                "Manually retry failed jobs",
                "Check storage and service connectivity"
            ]
        }
    ]
    
    for solution in solutions:
        print(f"❓ {solution['issue']}:")
        print("   Possible causes:")
        for cause in solution['causes']:
            print(f"     • {cause}")
        print("   Solutions:")
        for fix in solution['solutions']:
            print(f"     ✅ {fix}")
        print()


def main():
    """Main function to run all diagnostics"""
    # Load local settings first
    load_local_settings()
    
    # Reimport Config after reloading
    from config import Config
    
    success1 = query_jobs_table()
    success2 = check_queue_status()
    
    suggest_fixes()
    
    if success1 and success2:
        print("=" * 60)
        print("🎯 Table Storage Query: COMPLETED")
        print("\n💡 Next Steps:")
        print("   1. If jobs are stuck in 'queued' - check queue processing")
        print("   2. Use manual processing endpoint to unstick jobs")
        print("   3. Check Azure Functions app logs for errors")
        print("   4. Restart function app if needed")
    else:
        print("❌ Some diagnostics failed")
    
    return success1 and success2


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)