#!/usr/bin/env python3
"""
Detailed query for Service Bus task execution failures.

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
    print("DETAILED SERVICE BUS TASK EXECUTION ANALYSIS")
    print("=" * 80)

    token = get_access_token()

    # Query 1: Look for controller errors
    print("\n🔍 Searching for controller errors and exceptions...")

    query1 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'Controller' and (message contains 'failed' or message contains 'error' or message contains 'Error')
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data1 = query_logs(token, query1)
    if data1:
        results1 = format_results(data1)
        print(f"Found {len(results1)} controller error entries:")
        for entry in results1[:10]:
            print(f"  [{entry['timestamp']}] {entry['message'][:150]}")

    # Query 2: Look for AttributeError or similar
    print("\n🔍 Searching for AttributeError or TypeError...")

    query2 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'AttributeError' or message contains 'TypeError' or message contains 'has no attribute'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data2 = query_logs(token, query2)
    if data2:
        results2 = format_results(data2)
        print(f"Found {len(results2)} attribute/type error entries:")
        for entry in results2[:10]:
            print(f"  [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 3: Look for update_task related errors
    print("\n🔍 Searching for update_task errors...")

    query3 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'update_task' or message contains 'update_task_with_model'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data3 = query_logs(token, query3)
    if data3:
        results3 = format_results(data3)
        print(f"Found {len(results3)} update_task entries:")
        for entry in results3[:10]:
            print(f"  [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 4: Look for process_task_queue_message
    print("\n🔍 Searching for process_task_queue_message calls...")

    query4 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'process_task_queue_message' or message contains 'Controller processed task'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data4 = query_logs(token, query4)
    if data4:
        results4 = format_results(data4)
        print(f"Found {len(results4)} process_task_queue_message entries:")
        for entry in results4[:10]:
            print(f"  [{entry['timestamp']}] {entry['message'][:200]}")

    # Query 5: Look for any Traceback
    print("\n🔍 Searching for Python tracebacks...")

    query5 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'Traceback' or message contains 'File' and message contains 'line'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data5 = query_logs(token, query5)
    if data5:
        results5 = format_results(data5)
        print(f"Found {len(results5)} traceback entries:")
        for entry in results5[:5]:
            print(f"  [{entry['timestamp']}]")
            # Print full traceback
            lines = entry['message'].split('\\n')
            for line in lines[:10]:  # First 10 lines of traceback
                print(f"    {line}")

    # Query 6: Task handler execution
    print("\n🔍 Searching for TaskHandler execution...")

    query6 = """
    traces
    | where timestamp >= ago(30m)
    | where message contains 'TaskHandler' or message contains 'handler' or message contains 'hello_world_greeting'
    | project timestamp, message
    | order by timestamp desc
    | limit 50
    """

    data6 = query_logs(token, query6)
    if data6:
        results6 = format_results(data6)
        print(f"Found {len(results6)} task handler entries:")
        for entry in results6[:10]:
            print(f"  [{entry['timestamp']}] {entry['message'][:200]}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()