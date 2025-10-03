#!/usr/bin/env python3
"""
Query Application Insights for job completion trace.

Specifically looking for:
1. Task completion events
2. Stage advancement
3. Job completion attempts
4. Any errors during completion

Author: Robert and Geospatial Claude Legion
Date: 28 SEP 2025
"""

import json
import subprocess
import sys

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
        sys.exit(1)

def query_logs(token, query):
    """Execute a query against Application Insights."""
    import urllib.request
    import urllib.parse

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    params = urllib.parse.urlencode({"query": query})
    url = f"{API_ENDPOINT}?{params}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        return None

def format_results(data):
    """Format query results for display."""
    if not data or "tables" not in data or not data["tables"]:
        return []

    table = data["tables"][0]
    columns = [col["name"] for col in table["columns"]]
    rows = table["rows"]

    results = []
    for row in rows:
        result = dict(zip(columns, row))
        results.append(result)

    return results

def main():
    print("=" * 80)
    print("SERVICE BUS JOB COMPLETION TRACE")
    print("Job ID: 6080717a...")
    print("=" * 80)

    token = get_access_token()

    # Query 1: Look for stage completion and job completion attempts
    print("\n🔍 Stage/Job Completion Events...")

    query1 = """
    traces
    | where timestamp >= ago(5m)
    | where message contains '6080717a' or message contains 'stage_complete' or message contains 'Job completed' or message contains 'Complete job' or message contains 'Job 6080717a'
    | project timestamp, message
    | order by timestamp asc
    | limit 100
    """

    data1 = query_logs(token, query1)
    if data1:
        results1 = format_results(data1)
        print(f"Found {len(results1)} completion-related entries:")
        for i, entry in enumerate(results1):
            print(f"{i+1}. [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 2: Look for aggregate_job_results calls
    print("\n🔍 Job Aggregation Events...")

    query2 = """
    traces
    | where timestamp >= ago(5m)
    | where message contains 'aggregate' or message contains 'Aggregate' or message contains 'final_result'
    | project timestamp, message
    | order by timestamp asc
    | limit 50
    """

    data2 = query_logs(token, query2)
    if data2:
        results2 = format_results(data2)
        print(f"Found {len(results2)} aggregation entries:")
        for i, entry in enumerate(results2[:10]):
            print(f"{i+1}. [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 3: Look for StateManager complete_job calls
    print("\n🔍 StateManager complete_job Calls...")

    query3 = """
    traces
    | where timestamp >= ago(5m)
    | where message contains 'state_manager.complete_job' or message contains 'StateManager.complete_job' or message contains 'Completing job'
    | project timestamp, message
    | order by timestamp asc
    | limit 50
    """

    data3 = query_logs(token, query3)
    if data3:
        results3 = format_results(data3)
        print(f"Found {len(results3)} StateManager entries:")
        for i, entry in enumerate(results3[:10]):
            print(f"{i+1}. [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 4: Look for any errors or exceptions
    print("\n🔍 Errors/Exceptions during completion...")

    query4 = """
    traces
    | where timestamp >= ago(5m)
    | where (message contains '6080717a' or message contains 'complete_job' or message contains 'aggregate') 
        and (message contains 'Error' or message contains 'error' or message contains 'Exception' or message contains 'Failed')
    | project timestamp, message
    | order by timestamp asc
    | limit 50
    """

    data4 = query_logs(token, query4)
    if data4:
        results4 = format_results(data4)
        print(f"Found {len(results4)} error entries:")
        for i, entry in enumerate(results4[:10]):
            print(f"{i+1}. [{entry['timestamp']}] {entry['message'][:250]}")

    # Query 5: Look for get_tasks_for_job calls
    print("\n🔍 Task Fetching for Job Completion...")

    query5 = """
    traces
    | where timestamp >= ago(5m)
    | where message contains 'get_tasks_for_job' or message contains 'task_records' or message contains 'TaskRecord'
    | project timestamp, message
    | order by timestamp asc
    | limit 50
    """

    data5 = query_logs(token, query5)
    if data5:
        results5 = format_results(data5)
        print(f"Found {len(results5)} task fetching entries:")
        for i, entry in enumerate(results5[:10]):
            print(f"{i+1}. [{entry['timestamp']}] {entry['message'][:200]}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
