#!/usr/bin/env python3
"""
Query Application Insights logs for Service Bus task execution trace.

This script queries the Azure Application Insights logs to trace the execution
of Service Bus tasks and identify where they're getting stuck.

Author: Robert and Geospatial Claude Legion
Date: 28 SEP 2025
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta

# Application Insights App ID from the logs
APP_INSIGHTS_APP_ID = "829adb94-5f5c-46ae-9f00-18e731529222"
API_ENDPOINT = f"https://api.applicationinsights.io/v1/apps/{APP_INSIGHTS_APP_ID}/query"

def get_access_token():
    """Get Azure access token for Application Insights API."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://api.applicationinsights.io", "--query", "accessToken", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting access token: {e}")
        print("Please run: az login")
        sys.exit(1)

def query_logs(token, query):
    """Execute a query against Application Insights."""
    import urllib.request
    import urllib.parse

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # URL encode the query
    params = urllib.parse.urlencode({"query": query})
    url = f"{API_ENDPOINT}?{params}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        print(e.read().decode())
        return None

def format_results(data):
    """Format query results for display."""
    if not data or "tables" not in data or not data["tables"]:
        return "No results found"

    table = data["tables"][0]
    columns = [col["name"] for col in table["columns"]]
    rows = table["rows"]

    results = []
    for row in rows:
        result = dict(zip(columns, row))
        results.append(result)

    return results

def main():
    """Query logs for Service Bus task execution."""

    print("=" * 80)
    print("SERVICE BUS TASK EXECUTION TRACE")
    print("=" * 80)

    # Get access token
    print("\n🔑 Getting Azure access token...")
    token = get_access_token()
    print("✅ Token obtained")

    # Job ID from the Service Bus test
    job_id = "1be87186892cf687e912577714b5680f19542f1945c1c53040aeb5decd72dd7c"
    task_prefix = "1be87186"

    # Query 1: All logs related to our Service Bus job
    print(f"\n📋 Querying logs for job: {job_id[:16]}...")

    query1 = f"""
    traces
    | where timestamp >= ago(1h)
    | where message contains '{task_prefix}' or message contains 'sb_hello_world'
    | project timestamp, message, customDimensions
    | order by timestamp desc
    | limit 100
    """

    print("Executing query for job-related logs...")
    data1 = query_logs(token, query1)

    if data1:
        results1 = format_results(data1)
        print(f"\n📊 Found {len(results1)} log entries:")
        print("-" * 80)
        for i, entry in enumerate(results1[:20]):  # Show first 20
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            print(f"{i+1}. [{timestamp}] {message[:150]}")

    # Query 2: Error logs in the last hour
    print("\n\n❌ Querying for ERROR logs...")

    query2 = """
    traces
    | where timestamp >= ago(1h)
    | where message contains 'ERROR' or message contains 'Failed' or message contains 'Exception'
    | where message contains 'Service Bus' or message contains 'task' or message contains 'controller'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data2 = query_logs(token, query2)

    if data2:
        results2 = format_results(data2)
        print(f"\n📊 Found {len(results2)} error entries:")
        print("-" * 80)
        for i, entry in enumerate(results2[:20]):  # Show first 20
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            if "1be87186" in message or "sb_hello" in message or "Service Bus" in message:
                print(f"{i+1}. [{timestamp}] {message[:200]}")

    # Query 3: Controller processing logs
    print("\n\n🎯 Querying for controller processing logs...")

    query3 = f"""
    traces
    | where timestamp >= ago(1h)
    | where message contains 'Controller processing' or message contains 'controller.process_task_queue_message'
    | project timestamp, message
    | order by timestamp desc
    | limit 30
    """

    data3 = query_logs(token, query3)

    if data3:
        results3 = format_results(data3)
        print(f"\n📊 Found {len(results3)} controller processing entries:")
        print("-" * 80)
        for i, entry in enumerate(results3[:15]):
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            print(f"{i+1}. [{timestamp}] {message[:200]}")

    # Query 4: SQL function calls
    print("\n\n🔧 Querying for SQL function calls...")

    query4 = """
    traces
    | where timestamp >= ago(1h)
    | where message contains 'complete_task_and_check_stage' or message contains 'SQL completion'
    | project timestamp, message
    | order by timestamp desc
    | limit 30
    """

    data4 = query_logs(token, query4)

    if data4:
        results4 = format_results(data4)
        print(f"\n📊 Found {len(results4)} SQL function entries:")
        print("-" * 80)
        for i, entry in enumerate(results4[:15]):
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            print(f"{i+1}. [{timestamp}] {message[:200]}")

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()