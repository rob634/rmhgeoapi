#!/usr/bin/env python3
"""
Full STAC Inventory Script
Processes all geospatial files in bronze container through the STAC item service
Uses queue-based processing to avoid timeouts
"""

import os
import json
import time
import hashlib
from datetime import datetime
from azure.storage.blob import BlobServiceClient
import requests

# Configuration - Set these environment variables or update here
STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING', 'YOUR_CONNECTION_STRING_HERE')
BRONZE_CONTAINER = 'rmhazuregeobronze'
FUNCTION_URL = 'https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net'
FUNCTION_KEY = os.getenv('FUNCTION_KEY', 'YOUR_FUNCTION_KEY_HERE')

# Geospatial file extensions
GEOSPATIAL_EXTENSIONS = {
    '.tif', '.tiff', '.geotiff', '.geotif',  # Raster
    '.shp', '.shx', '.dbf', '.prj',  # Shapefile components
    '.geojson', '.json',  # GeoJSON
    '.gpkg',  # GeoPackage
    '.kml', '.kmz',  # KML
}

def list_geospatial_files():
    """List all geospatial files in bronze container"""
    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(BRONZE_CONTAINER)
    
    files = []
    for blob in container_client.list_blobs():
        ext = os.path.splitext(blob.name)[1].lower()
        if ext in GEOSPATIAL_EXTENSIONS:
            files.append({
                'name': blob.name,
                'size': blob.size,
                'extension': ext
            })
    
    return sorted(files, key=lambda x: x['size'])  # Process smaller files first

def determine_mode(file_info):
    """Determine whether to use quick or full mode based on file characteristics"""
    size_mb = file_info['size'] / (1024 * 1024)
    ext = file_info['extension']
    
    # Large files always use quick mode to avoid timeouts
    if size_mb > 500:  # 500MB threshold
        return 'quick'
    
    # Vector files < 100MB use full mode for geometry extraction
    if ext in ['.geojson', '.json', '.gpkg'] and size_mb < 100:
        return 'full'
    
    # Small rasters use full mode for bbox extraction
    if ext in ['.tif', '.tiff', '.geotiff'] and size_mb < 50:
        return 'full'
    
    # Default to quick
    return 'quick'

def submit_stac_job(file_name, mode):
    """Submit STAC item job to Azure Function"""
    operation = f"stac_item_{mode}"
    
    payload = {
        'dataset_id': BRONZE_CONTAINER,
        'resource_id': file_name,
        'version_id': mode
    }
    
    headers = {
        'Content-Type': 'application/json',
        'x-functions-key': FUNCTION_KEY
    }
    
    url = f"{FUNCTION_URL}/api/jobs/{operation}"
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'job_id': data.get('job_id'),
                'is_duplicate': data.get('is_duplicate', False)
            }
        else:
            return {
                'success': False,
                'error': f"HTTP {response.status_code}"
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def check_job_status(job_id):
    """Check status of a submitted job"""
    url = f"{FUNCTION_URL}/api/jobs/{job_id}"
    headers = {'x-functions-key': FUNCTION_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('status', 'unknown')
        return 'error'
    except:
        return 'error'

def main():
    print("=== Full STAC Inventory Script ===")
    print(f"Container: {BRONZE_CONTAINER}")
    print(f"Started: {datetime.now().isoformat()}")
    print()
    
    # Step 1: List all geospatial files
    print("Listing geospatial files...")
    files = list_geospatial_files()
    print(f"Found {len(files)} geospatial files")
    
    # Show size distribution
    total_size = sum(f['size'] for f in files)
    print(f"Total size: {total_size / (1024**3):.2f} GB")
    print()
    
    # Step 2: Process each file
    results = {
        'submitted': 0,
        'duplicates': 0,
        'failed': 0,
        'quick_mode': 0,
        'full_mode': 0
    }
    
    job_tracker = []  # Track job IDs for status checking
    
    print("Submitting jobs to queue...")
    print("-" * 60)
    
    for i, file_info in enumerate(files, 1):
        mode = determine_mode(file_info)
        
        # Update mode counters
        if mode == 'quick':
            results['quick_mode'] += 1
        else:
            results['full_mode'] += 1
        
        # Submit job
        print(f"[{i}/{len(files)}] {file_info['name'][:50]} ({file_info['size']/1024/1024:.1f}MB) - {mode} mode", end=' ... ')
        
        result = submit_stac_job(file_info['name'], mode)
        
        if result['success']:
            if result['is_duplicate']:
                print("DUPLICATE")
                results['duplicates'] += 1
            else:
                print("QUEUED")
                results['submitted'] += 1
                job_tracker.append({
                    'job_id': result['job_id'],
                    'file': file_info['name'],
                    'mode': mode
                })
        else:
            print(f"FAILED: {result['error']}")
            results['failed'] += 1
        
        # Small delay to avoid overwhelming the API
        if i % 10 == 0:
            time.sleep(1)
    
    print("-" * 60)
    print()
    
    # Step 3: Wait for jobs to complete
    if job_tracker:
        print(f"Waiting for {len(job_tracker)} jobs to complete...")
        print("(This may take several minutes for full mode processing)")
        
        # Check status periodically
        completed = 0
        last_check = 0
        max_wait = 600  # 10 minutes max
        start_time = time.time()
        
        while completed < len(job_tracker) and (time.time() - start_time) < max_wait:
            time.sleep(10)  # Check every 10 seconds
            
            # Sample check on a few jobs
            sample_size = min(5, len(job_tracker))
            sample_completed = 0
            
            for job in job_tracker[:sample_size]:
                status = check_job_status(job['job_id'])
                if status in ['completed', 'failed']:
                    sample_completed += 1
            
            # Estimate completion
            estimated_complete = int((sample_completed / sample_size) * len(job_tracker))
            if estimated_complete != last_check:
                print(f"  Progress: ~{estimated_complete}/{len(job_tracker)} jobs completed")
                last_check = estimated_complete
            
            if sample_completed == sample_size:
                completed = len(job_tracker)  # All done
    
    # Step 4: Summary
    print()
    print("=== Inventory Complete ===")
    print(f"Files processed: {len(files)}")
    print(f"  - Quick mode: {results['quick_mode']}")
    print(f"  - Full mode: {results['full_mode']}")
    print(f"Jobs submitted: {results['submitted']}")
    print(f"Duplicates skipped: {results['duplicates']}")
    print(f"Failed: {results['failed']}")
    print(f"Completed: {datetime.now().isoformat()}")

if __name__ == "__main__":
    main()