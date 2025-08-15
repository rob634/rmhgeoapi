#!/usr/bin/env python3
"""
Direct query to Azure Table Storage to check job statuses
Bypasses Config class issues by using connection string directly
"""
import json
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient


def direct_query_jobs():
    """Query jobs table directly using connection string"""
    print("🔍 Direct Query to Jobs Table Storage")
    print("=" * 60)
    
    # Load connection string from local.settings.json
    try:
        with open('local.settings.json', 'r') as f:
            settings = json.load(f)
            connection_string = settings['Values']['AzureWebJobsStorage']
            print("✅ Loaded connection string from local.settings.json")
    except Exception as e:
        print(f"❌ Error loading connection string: {e}")
        return False
    
    try:
        # Connect directly to Table Storage
        table_service = TableServiceClient.from_connection_string(connection_string)
        from constants import AzureStorage
        table_name = AzureStorage.JOB_TRACKING_TABLE
        table_client = table_service.get_table_client(table_name)
        
        print(f"✅ Connected to table: {table_name}")
        
        # Query all jobs
        print(f"\n📊 Querying all jobs...")
        entities = list(table_client.query_entities("PartitionKey eq 'jobs'"))
        
        if not entities:
            print("📭 No jobs found in table")
            return True
        
        print(f"📋 Found {len(entities)} jobs in table")
        print("=" * 60)
        
        # Analyze jobs by status
        status_counts = {}
        recent_jobs = []
        
        for entity in entities:
            status = entity.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Collect recent jobs (last 10)
            if len(recent_jobs) < 10:
                recent_jobs.append(entity)
        
        # Show status summary
        print("📈 Job Status Summary:")
        for status, count in status_counts.items():
            print(f"   {status}: {count} jobs")
        
        # Show recent jobs in detail
        print(f"\n📋 Recent Jobs (showing {len(recent_jobs)}):")
        print("-" * 60)
        
        for i, job in enumerate(recent_jobs, 1):
            job_id = job.get('RowKey', 'unknown')
            short_id = job_id[:16] + "..." if len(job_id) > 16 else job_id
            
            dataset_id = job.get('dataset_id', 'N/A')
            resource_id = job.get('resource_id', 'N/A') 
            operation_type = job.get('operation_type', 'N/A')
            status = job.get('status', 'N/A')
            system = job.get('system', False)
            created_at = job.get('created_at', 'N/A')
            updated_at = job.get('updated_at', 'N/A')
            
            print(f"{i:2d}. Job ID: {short_id}")
            print(f"    📊 Dataset: {dataset_id}")
            print(f"    📁 Resource: {resource_id[:30]}{'...' if len(resource_id) > 30 else ''}")
            print(f"    🔧 Operation: {operation_type}")
            print(f"    📊 Status: {status}")
            print(f"    🏷️ System: {system}")
            print(f"    📅 Created: {created_at}")
            print(f"    🔄 Updated: {updated_at}")
            
            # Check for result data
            if 'result_data' in job and job['result_data']:
                print(f"    ✅ Has result data: Yes")
            
            # Check for error message
            if 'error_message' in job and job['error_message']:
                print(f"    ❌ Error: {job['error_message'][:50]}...")
            
            # Check for request parameters (new field)
            if 'request_parameters' in job:
                print(f"    📋 Has full request params: Yes")
            else:
                print(f"    📋 Has full request params: No")
            
            print()
        
        # Analyze stuck jobs
        print("🔍 Analyzing Job Processing Times:")
        print("-" * 40)
        
        current_time = datetime.now(timezone.utc)
        stuck_jobs = []
        processing_times = []
        
        for entity in entities:
            status = entity.get('status')
            created_at = entity.get('created_at')
            updated_at = entity.get('updated_at')
            
            if created_at and updated_at:
                try:
                    created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    age_minutes = (current_time - created).total_seconds() / 60
                    processing_time = (updated - created).total_seconds()
                    
                    processing_times.append(processing_time)
                    
                    # Jobs that are stuck in non-final states
                    if status in ['queued', 'processing'] and age_minutes > 2:
                        stuck_jobs.append({
                            'job_id': entity.get('RowKey', 'unknown')[:16] + "...",
                            'status': status,
                            'age_minutes': age_minutes,
                            'operation': entity.get('operation_type', 'N/A'),
                            'dataset': entity.get('dataset_id', 'N/A')[:20]
                        })
                except:
                    pass
        
        if processing_times:
            avg_processing = sum(processing_times) / len(processing_times)
            print(f"   📊 Average processing time: {avg_processing:.1f} seconds")
            print(f"   ⚡ Fastest job: {min(processing_times):.1f} seconds")
            print(f"   🐌 Slowest job: {max(processing_times):.1f} seconds")
        
        if stuck_jobs:
            print(f"\n⚠️ Found {len(stuck_jobs)} potentially stuck jobs:")
            for job in stuck_jobs[:5]:  # Show first 5
                print(f"   🆔 {job['job_id']} - {job['status']} for {job['age_minutes']:.1f} min")
                print(f"      Operation: {job['operation']}, Dataset: {job['dataset']}")
        else:
            print("✅ No stuck jobs found (all completed or very recent)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error querying table: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_queue_directly():
    """Check Azure Storage Queue directly"""
    print(f"\n📬 Direct Queue Status Check")
    print("=" * 60)
    
    try:
        # Load connection string
        with open('local.settings.json', 'r') as f:
            settings = json.load(f)
            connection_string = settings['Values']['AzureWebJobsStorage']
        
        from azure.storage.queue import QueueServiceClient
        queue_service = QueueServiceClient.from_connection_string(connection_string)
        from constants import AzureStorage
        queue_name = AzureStorage.JOB_PROCESSING_QUEUE
        
        try:
            queue_client = queue_service.get_queue_client(queue_name)
            properties = queue_client.get_queue_properties()
            message_count = properties.approximate_message_count
            
            print(f"📬 Queue: {queue_name}")
            print(f"📊 Messages waiting: {message_count}")
            
            if message_count > 0:
                print("⚠️ ISSUE: Messages waiting in queue but not being processed")
                print("💡 This suggests Azure Functions queue trigger is not working")
                
                # Try to peek at messages
                try:
                    messages = queue_client.peek_messages(max_messages=3)
                    if messages:
                        print(f"\n📄 Sample queued messages:")
                        for i, msg in enumerate(messages, 1):
                            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                            print(f"   {i}. {content}")
                            print(f"      Added: {msg.insertion_time}")
                except Exception as e:
                    print(f"   Could not peek messages: {e}")
            else:
                print("✅ Queue is empty - jobs are being processed normally")
            
            return True
            
        except Exception as e:
            print(f"❌ Queue '{queue_name}' not found or accessible: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking queue: {e}")
        return False


def main():
    """Run direct table queries"""
    print("🕵️ Direct Azure Storage Investigation")
    print("=" * 70)
    
    success1 = direct_query_jobs()
    success2 = check_queue_directly()
    
    print("\n" + "=" * 70)
    if success1 and success2:
        print("✅ Direct storage query completed successfully")
        print("\n💡 Analysis Summary:")
        print("   1. Check job statuses above - look for stuck 'queued' jobs")
        print("   2. If queue has messages, the trigger isn't working")
        print("   3. Use manual processing to unstick jobs if needed")
    else:
        print("❌ Some queries failed")
    
    return success1 and success2


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)