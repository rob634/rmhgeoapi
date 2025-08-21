#!/usr/bin/env python3
"""
Manual script to sync Bronze container files to STAC catalog
This bypasses Azure Functions complexity for direct testing
"""

import os
import json
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

# Configuration - hardcoded per user request
DB_CONFIG = {
    'host': 'rmhpgflex.postgres.database.azure.com',
    'port': 5432,
    'dbname': 'geopgflex',
    'user': 'rob634',
    'password': 'B@lamb634@',
    'sslmode': 'require'
}

# Azure Storage - use connection string for local, managed identity in production
STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING', 'YOUR_CONNECTION_STRING_HERE')
STORAGE_ACCOUNT_NAME = 'rmhazuregeo'  # Corrected storage account name
BRONZE_CONTAINER = 'rmhazuregeobronze'

# Geospatial file extensions to sync
GEOSPATIAL_EXTENSIONS = {
    '.tif', '.tiff', '.geotiff', '.geotif',  # Raster
    '.shp', '.shx', '.dbf', '.prj',  # Shapefile
    '.geojson', '.json',  # GeoJSON
    '.gpkg',  # GeoPackage
    '.kml', '.kmz',  # KML
}

def ensure_collection_exists(conn, container_name):
    """Create or update the STAC collection for the container"""
    collection_id = f"container_{container_name}"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Create collection
        cur.execute("""
            INSERT INTO geo.collections (
                id, title, description, keywords, license
            ) VALUES (
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
        """, (
            collection_id,
            f"Azure Container: {container_name}",
            f"STAC collection for Azure Storage container '{container_name}'",
            [container_name, 'bronze', 'sync'],  # Array as Python list
            'proprietary'
        ))
        
        result = cur.fetchone()
        conn.commit()
        print(f"✓ Collection ensured: {result['id']}")
        return result['id']

def list_geospatial_blobs(container_name):
    """List all geospatial files in the container"""
    blobs = []
    
    try:
        # Use connection string for local testing
        blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
        container_client = blob_service.get_container_client(container_name)
        
        for blob in container_client.list_blobs():
            # Check if geospatial file
            ext = os.path.splitext(blob.name)[1].lower()
            if ext in GEOSPATIAL_EXTENSIONS:
                blobs.append({
                    'name': blob.name,
                    'size': blob.size,
                    'last_modified': blob.last_modified,
                    'content_type': blob.content_settings.content_type if blob.content_settings else 'application/octet-stream',
                    'etag': blob.etag
                })
                
    except Exception as e:
        print(f"❌ Error listing blobs: {e}")
    
    return blobs

def create_stac_item(conn, collection_id, container_name, blob):
    """Create or update a STAC item for a blob"""
    import hashlib
    
    # Generate base ID
    base_id = f"{container_name}_{blob['name'].replace('/', '_')}"
    
    # If ID is too long, use hash instead (but keep full path in properties)
    if len(base_id) > 250:  # Leave some margin
        # Use MD5 hash of the full path for uniqueness
        path_hash = hashlib.md5(blob['name'].encode()).hexdigest()
        # Include just the filename at the end for human readability
        filename = os.path.basename(blob['name'])
        if len(filename) > 50:
            filename = filename[:47] + "..."
        item_id = f"{container_name}_{path_hash}_{filename}"
        if len(item_id) > 250:
            # If still too long, just use hash
            item_id = f"{container_name}_{path_hash}"
    else:
        item_id = base_id
    
    # Create basic geometry (polygon - bbox around point 0,0)
    # This should be extracted from actual file in production
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [-0.001, -0.001],  # SW corner
            [0.001, -0.001],   # SE corner
            [0.001, 0.001],    # NE corner
            [-0.001, 0.001],   # NW corner
            [-0.001, -0.001]   # Close polygon
        ]]
    }
    
    # Create properties - ALWAYS store full path for Bronze→Silver processing
    properties = {
        "datetime": blob['last_modified'].isoformat(),
        "file:size": blob['size'],
        "file:path": blob['name'],  # Full Bronze path preserved for lineage
        "file:content_type": blob['content_type'],
        "sync:source": "manual_sync",
        "sync:timestamp": datetime.now(timezone.utc).isoformat(),
        # For crazy vendor paths, we might add a "clean_name" in Silver processing
        "file:basename": os.path.basename(blob['name'])
    }
    
    # Create assets
    assets = {
        "data": {
            "href": f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container_name}/{blob['name']}",
            "type": blob['content_type'],
            "roles": ["data"]
        }
    }
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check if item exists
        cur.execute("""
            SELECT id FROM geo.items WHERE id = %s
        """, (item_id,))
        
        exists = cur.fetchone()
        
        if exists:
            # Update existing
            cur.execute("""
                UPDATE geo.items SET
                    geometry = ST_GeomFromGeoJSON(%s),
                    datetime = %s,
                    properties = %s,
                    assets = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
            """, (
                json.dumps(geometry),
                blob['last_modified'],
                Json(properties),
                Json(assets),
                item_id
            ))
            print(f"  ↻ Updated: {blob['name']}")
        else:
            # Create new
            cur.execute("""
                INSERT INTO geo.items (
                    id, collection_id, geometry, datetime,
                    properties, assets, stac_version
                ) VALUES (
                    %s, %s, ST_GeomFromGeoJSON(%s), %s,
                    %s, %s, %s
                )
                RETURNING id
            """, (
                item_id,
                collection_id,
                json.dumps(geometry),
                blob['last_modified'],
                Json(properties),
                Json(assets),
                '1.0.0'
            ))
            print(f"  ✓ Created: {blob['name']}")
        
        conn.commit()

def main():
    """Main sync process"""
    print(f"=== STAC Bronze Container Sync ===")
    print(f"Container: {BRONZE_CONTAINER}")
    print()
    
    # Step 1: Connect to database
    try:
        print("Connecting to PostgreSQL...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("✓ Connected to database")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    try:
        # Step 2: Ensure collection exists
        collection_id = ensure_collection_exists(conn, BRONZE_CONTAINER)
        
        # Step 3: List geospatial blobs
        print(f"\nListing geospatial files in {BRONZE_CONTAINER}...")
        blobs = list_geospatial_blobs(BRONZE_CONTAINER)
        print(f"✓ Found {len(blobs)} geospatial files")
        
        if not blobs:
            print("\nNo geospatial files found to sync")
            return
        
        # Step 4: Process each blob
        print(f"\nSyncing files to STAC catalog...")
        success_count = 0
        for i, blob in enumerate(blobs, 1):
            print(f"\n[{i}/{len(blobs)}] Processing {blob['name']}...")
            try:
                create_stac_item(conn, collection_id, BRONZE_CONTAINER, blob)
                success_count += 1
            except Exception as e:
                print(f"  ❌ Error: {e}")
                conn.rollback()  # Rollback on error to reset transaction
        
        # Step 5: Summary
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM geo.items 
                WHERE collection_id = %s
            """, (collection_id,))
            result = cur.fetchone()
            
            print(f"\n=== Sync Complete ===")
            print(f"✓ Successfully synced: {success_count}/{len(blobs)} files")
            print(f"✓ Total items in collection: {result['count']}")
            
            # Show sample items
            cur.execute("""
                SELECT id, properties->>'file:path' as path,
                       properties->>'file:size' as size
                FROM geo.items
                WHERE collection_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            """, (collection_id,))
            
            items = cur.fetchall()
            if items:
                print(f"\nRecent items:")
                for item in items:
                    size_mb = int(item['size'] or 0) / (1024*1024)
                    print(f"  - {item['path']} ({size_mb:.2f} MB)")
    
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()
        print("\nDatabase connection closed")

if __name__ == "__main__":
    main()