import psycopg
import json

# Database connection
conn_str = "host=rmhpgflex.postgres.database.azure.com dbname=geopgflex user=rob634 password=B@lamb634@ sslmode=require"

query = """
    SELECT 
        id,
        properties->>'asset_href' as asset_href,
        properties->>'href' as href,
        properties->>'container' as container,
        properties->>'blob_name' as blob_name,
        properties->>'file_size' as file_size,
        jsonb_pretty(properties) as full_props
    FROM geo.items 
    WHERE id = '9688674d025c992478d849c687c40a52'
"""

with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()
        if result:
            print(f"ID: {result[0]}")
            print(f"asset_href: {result[1]}")
            print(f"href: {result[2]}")
            print(f"container: {result[3]}")
            print(f"blob_name: {result[4]}")
            print(f"file_size: {result[5]}")
            print("\nFull properties (first 1000 chars):")
            print(result[6][:1000] if result[6] else "None")
