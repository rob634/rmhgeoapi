#!/usr/bin/env python3
"""
Service Bus Queue Diagnostic Tool

Peeks at messages in Service Bus queues to debug why they're not triggering.

Usage:
    python debug_service_bus.py

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

import os
import json
from datetime import datetime
from azure.servicebus import ServiceBusClient
from azure.identity import DefaultAzureCredential

def check_service_bus_queues():
    """Peek at messages in Service Bus queues."""

    # Get connection info from environment or use connection string
    connection_string = os.getenv('ServiceBusConnection')

    if not connection_string:
        # Use DefaultAzureCredential
        namespace = os.getenv('SERVICE_BUS_NAMESPACE', 'rmhgeoapi')
        credential = DefaultAzureCredential()
        client = ServiceBusClient(
            fully_qualified_namespace=f"{namespace}.servicebus.windows.net",
            credential=credential
        )
    else:
        client = ServiceBusClient.from_connection_string(connection_string)

    queues_to_check = ['jobs', 'tasks', 'sb-jobs', 'sb-tasks']

    print("=" * 80)
    print(f"Service Bus Queue Diagnostics - {datetime.now()}")
    print("=" * 80)

    for queue_name in queues_to_check:
        try:
            with client:
                receiver = client.get_queue_receiver(queue_name)

                with receiver:
                    # Peek at messages without consuming
                    messages = receiver.peek_messages(max_message_count=10)

                    print(f"\n📦 Queue: {queue_name}")
                    print(f"   Message Count: {len(messages)}")

                    if messages:
                        print("   Messages (peeked, not consumed):")
                        for i, msg in enumerate(messages, 1):
                            # Parse message body
                            try:
                                body = str(msg)
                                if body.startswith('{'):
                                    body_json = json.loads(body)
                                    job_id = body_json.get('job_id', 'N/A')
                                    job_type = body_json.get('job_type', 'N/A')
                                    print(f"      {i}. Job ID: {job_id}, Type: {job_type}")
                                    print(f"         Enqueued: {msg.enqueued_time_utc}")
                                    print(f"         Sequence: {msg.sequence_number}")
                                else:
                                    print(f"      {i}. Raw: {body[:100]}...")
                            except Exception as e:
                                print(f"      {i}. Parse error: {e}")
                    else:
                        print("   ✅ Queue is empty")

        except Exception as e:
            print(f"\n❌ Error checking queue '{queue_name}': {e}")
            print(f"   (Queue might not exist or no access)")

    print("\n" + "=" * 80)
    print("Diagnostic complete")
    print("=" * 80)

def check_function_app_settings():
    """Check if Function App has correct Service Bus settings."""

    print("\n🔧 Checking local Service Bus configuration...")

    # Check for connection string
    conn_string = os.getenv('ServiceBusConnection')
    if conn_string:
        print("✅ ServiceBusConnection found in environment")
        # Don't print the actual connection string for security
        print(f"   Length: {len(conn_string)} characters")
        if "Endpoint=sb://" in conn_string:
            print("   Format looks correct (starts with Endpoint=sb://)")
    else:
        print("❌ ServiceBusConnection not found")
        print("   Add to local.settings.json or Azure Function App settings")

    # Check for namespace
    namespace = os.getenv('SERVICE_BUS_NAMESPACE')
    if namespace:
        print(f"✅ SERVICE_BUS_NAMESPACE: {namespace}")
    else:
        print("⚠️  SERVICE_BUS_NAMESPACE not set (optional if using connection string)")

def check_trigger_configuration():
    """Show what the Service Bus triggers expect."""

    print("\n📋 Expected Service Bus Trigger Configuration:")
    print("   From function_app.py:")
    print("   - Job trigger expects queue: 'jobs' (not 'sb-jobs')")
    print("   - Task trigger expects queue: 'tasks' (not 'sb-tasks')")
    print("   - Connection setting name: 'ServiceBusConnection'")
    print("\n   Note: The queues use the SAME names as Storage Queues")
    print("         The routing happens via the repository selection")

if __name__ == "__main__":
    # Check configuration
    check_function_app_settings()
    check_trigger_configuration()

    # Check queues
    try:
        check_service_bus_queues()
    except Exception as e:
        print(f"\n❌ Failed to connect to Service Bus: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure ServiceBusConnection is in local.settings.json")
        print("2. Or set SERVICE_BUS_NAMESPACE and use DefaultAzureCredential")
        print("3. Check that Service Bus namespace exists in Azure")
        print("4. Verify queues are created: jobs, tasks")