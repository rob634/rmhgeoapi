#!/usr/bin/env python3

"""
Debug completion detection issue by testing PostgreSQL function directly
"""

import os
import psycopg

def test_check_job_completion():
    """Test the check_job_completion function directly"""
    
    # Use hardcoded PostgreSQL connection
    conn_string = "postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/geopgflex"
    
    job_id = "617b5389fbb69efb4224af6b203cc5c5024f6838035d623376992a548723441b"
    
    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cursor:
            # First check what's in the jobs table
            print("=== JOBS TABLE (app schema) ===")
            cursor.execute("SELECT * FROM app.jobs WHERE job_id = %s", (job_id,))
            job = cursor.fetchone()
            if job:
                print(f"Job found: {job}")
            else:
                print("No job found!")
                return
            
            print("\n=== TASKS TABLE (app schema) ===")
            cursor.execute("SELECT task_id, parent_job_id, task_type, status, stage, task_index FROM app.tasks WHERE parent_job_id = %s", (job_id,))
            tasks = cursor.fetchall()
            if tasks:
                for task in tasks:
                    print(f"Task: {task}")
            else:
                print("No tasks found!")
                return
            
            print("\n=== TESTING check_job_completion FUNCTION ===")
            try:
                cursor.execute("SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM app.check_job_completion(%s)", (job_id,))
                result = cursor.fetchone()
                print(f"Function result: {result}")
            except Exception as e:
                print(f"Function error: {e}")
                print(f"Error type: {type(e).__name__}")
                
                # Try to get more details about the function
                print("\n=== FUNCTION DETAILS ===")
                cursor.execute("SELECT routine_name, data_type FROM information_schema.routines WHERE routine_schema = 'app' AND routine_name = 'check_job_completion'")
                func_info = cursor.fetchall()
                print(f"Function info: {func_info}")

if __name__ == "__main__":
    test_check_job_completion()