#!/usr/bin/env python3
"""
Query for the full traceback error.
"""

import json
import subprocess
import sys
import urllib.request
import urllib.parse

APP_INSIGHTS_APP_ID = "829adb94-5f5c-46ae-9f00-18e731529222"
API_ENDPOINT = f"https://api.applicationinsights.io/v1/apps/{APP_INSIGHTS_APP_ID}/query"

def get_access_token():
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://api.applicationinsights.io", "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)

def query_logs(token, query):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = urllib.parse.urlencode({"query": query})
    url = f"{API_ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        return None

def main():
    token = get_access_token()
    
    # Get the full traceback
    query = """
    traces
    | where timestamp >= ago(5m)
    | where message contains 'Traceback' or message contains 'line 759' or message contains 'get_tasks_for_job'
    | project timestamp, message
    | order by timestamp asc
    | limit 10
    """
    
    data = query_logs(token, query)
    if data and "tables" in data and data["tables"]:
        table = data["tables"][0]
        columns = [col["name"] for col in table["columns"]]
        
        for row in table["rows"]:
            result = dict(zip(columns, row))
            print(f"\n[{result['timestamp']}]")
            # Print full message with proper newline handling
            message = result['message'].replace('\\n', '\n')
            print(message)

if __name__ == "__main__":
    main()
