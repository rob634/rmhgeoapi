#!/usr/bin/env python3
"""
Analyze container_contents job outputs by downloading task results to DataFrame.

Downloads all task results from a completed list_container_contents job,
stores them in a pandas DataFrame, and optionally saves to local files.

Usage:
    python analyze_container_contents.py <job_id>
    python analyze_container_contents.py 8be5de7a789d0c9bb9c24c8d9e3dd313328b7690fbb8150e8e5082619be39b26
"""

import sys
import json
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configuration
API_BASE_URL = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net"
OUTPUT_DIR = Path(__file__).parent / "output"


class ContainerContentsAnalyzer:
    """Download and analyze list_container_contents job results."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.tasks_url = f"{API_BASE_URL}/api/db/tasks/{job_id}"
        self.job_url = f"{API_BASE_URL}/api/jobs/status/{job_id}"
        self.output_dir = OUTPUT_DIR / job_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def fetch_job_info(self) -> Dict[str, Any]:
        """Fetch job metadata."""
        print(f"📊 Fetching job info for {self.job_id[:16]}...")
        response = requests.get(self.job_url)
        response.raise_for_status()
        return response.json()

    def fetch_all_tasks(self, limit: int = 10000) -> List[Dict[str, Any]]:
        """Fetch all tasks for the job."""
        print(f"📥 Fetching all tasks (limit={limit})...")
        response = requests.get(f"{self.tasks_url}?limit={limit}")
        response.raise_for_status()
        data = response.json()

        tasks = data.get('tasks', [])
        total = data.get('query_info', {}).get('total_tasks', len(tasks))

        print(f"✅ Fetched {len(tasks)} tasks (total: {total})")
        return tasks

    def categorize_file_type(self, ext: str, blob_name: str) -> str:
        """Categorize file into vector, raster, metadata, or other."""
        ext_lower = ext.lower()

        # Vector formats
        vector_exts = {'.shp', '.dbf', '.prj', '.shx', '.geojson', '.json', '.kml', '.gpkg', '.gdb'}
        if ext_lower in vector_exts:
            return 'vector'

        # Raster formats
        raster_exts = {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.bmp'}
        if ext_lower in raster_exts:
            return 'raster'

        # Metadata/documentation
        metadata_exts = {'.xml', '.txt', '.md', '.imd', '.rpb', '.til', '.man'}
        if ext_lower in metadata_exts or 'readme' in blob_name.lower():
            return 'metadata'

        # Folders
        if ext_lower == 'no_extension':
            return 'folder'

        return 'other'

    def tasks_to_dataframe(self, tasks: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert tasks list to pandas DataFrame with extracted result data."""
        print(f"🔄 Converting {len(tasks)} tasks to DataFrame...")

        rows = []
        for task in tasks:
            # Base task info
            row = {
                'task_id': task.get('task_id'),
                'task_type': task.get('task_type'),
                'status': task.get('status'),
                'stage': task.get('stage'),
                'task_index': task.get('task_index'),
                'created_at': task.get('created_at'),
                'updated_at': task.get('updated_at'),
                'retry_count': task.get('retry_count', 0),
            }

            # Extract result data if available
            result_data = task.get('result_data', {})
            if isinstance(result_data, dict):
                result = result_data.get('result', {})

                # For Stage 1 (list_container_blobs)
                if task.get('task_type') == 'list_container_blobs':
                    row['blob_count'] = len(result.get('blob_names', []))
                    row['total_count'] = result.get('total_count')
                    row['scan_duration_seconds'] = result.get('execution_info', {}).get('scan_duration_seconds')
                    row['blobs_filtered'] = result.get('execution_info', {}).get('blobs_filtered', 0)

                # For Stage 2 (analyze_single_blob)
                elif task.get('task_type') == 'analyze_single_blob':
                    if isinstance(result, dict):
                        blob_name = result.get('blob_name', '')
                        file_ext = result.get('file_extension', '')

                        row['blob_name'] = blob_name
                        row['blob_path'] = result.get('blob_path')
                        row['size_bytes'] = result.get('size_bytes', 0)
                        row['size_mb'] = result.get('size_mb', 0)
                        row['file_extension'] = file_ext
                        row['content_type'] = result.get('content_type')
                        row['last_modified'] = result.get('last_modified')
                        row['etag'] = result.get('etag')

                        # Extract metadata
                        metadata = result.get('metadata', {})
                        row['is_folder'] = metadata.get('hdi_isfolder') == 'true'
                        row['metadata_keys'] = ','.join(metadata.keys()) if metadata else None

                        # Categorize file type
                        row['file_category'] = self.categorize_file_type(file_ext, blob_name)

                        # Extract base filename for duplicate detection
                        # Remove extension and path
                        if '/' in blob_name:
                            base_name = blob_name.split('/')[-1]
                        else:
                            base_name = blob_name

                        if '.' in base_name and file_ext != 'no_extension':
                            base_name = base_name.rsplit('.', 1)[0]

                        row['base_filename'] = base_name

            # Error details
            row['error_details'] = task.get('error_details')
            row['success'] = result_data.get('success', False) if isinstance(result_data, dict) else False

            rows.append(row)

        df = pd.DataFrame(rows)

        # Convert timestamps
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'])
        if 'updated_at' in df.columns:
            df['updated_at'] = pd.to_datetime(df['updated_at'])
        if 'last_modified' in df.columns:
            df['last_modified'] = pd.to_datetime(df['last_modified'], errors='coerce')

        print(f"✅ Created DataFrame: {df.shape[0]} rows, {df.shape[1]} columns")
        return df

    def save_raw_json(self, tasks: List[Dict[str, Any]]) -> Path:
        """Save raw task JSON to file."""
        output_file = self.output_dir / "tasks_raw.json"
        print(f"💾 Saving raw JSON to {output_file}")

        with open(output_file, 'w') as f:
            json.dump(tasks, f, indent=2, default=str)

        print(f"✅ Saved {len(tasks)} tasks to {output_file}")
        return output_file

    def save_dataframe(self, df: pd.DataFrame, format: str = 'csv') -> Path:
        """Save DataFrame to file (CSV or Parquet)."""
        if format == 'csv':
            output_file = self.output_dir / "tasks_data.csv"
            print(f"💾 Saving CSV to {output_file}")
            df.to_csv(output_file, index=False)
        elif format == 'parquet':
            output_file = self.output_dir / "tasks_data.parquet"
            print(f"💾 Saving Parquet to {output_file}")
            df.to_parquet(output_file, index=False)
        else:
            raise ValueError(f"Unsupported format: {format}")

        print(f"✅ Saved DataFrame to {output_file}")
        return output_file

    def analyze_folder_patterns(self, df: pd.DataFrame):
        """Detect and categorize folder/file organizational patterns."""
        import re

        stage2 = df[df['stage'] == 2].copy()
        if 'blob_name' not in stage2.columns or len(stage2) == 0:
            return

        patterns = {}

        for _, row in stage2.iterrows():
            name = row.get('blob_name', '')
            size = row.get('size_mb', 0)
            ext = row.get('file_extension', '')

            if '/' not in name:
                continue

            parts = name.split('/')
            top = parts[0]

            # Maxar order pattern (numeric GUID)
            if top.isdigit() and len(top) > 15:
                self._add_pattern(patterns, "PATTERN: Maxar Order (numeric GUID)", name, size, ext)

            # UUID pattern (Vivid basemaps)
            elif re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', top):
                self._add_pattern(patterns, "PATTERN: Vivid Basemap (UUID)", name, size, ext)

            # Maxar delivery subfolder
            if 'maxar_delivery' in name.lower():
                self._add_pattern(patterns, "PATTERN: Maxar Delivery Folder", name, size, ext)

            # Product types
            if '_P001_PSH' in name:
                self._add_pattern(patterns, "PRODUCT: Pansharpened Imagery", name, size, ext)
            elif '_P001_MUL' in name:
                self._add_pattern(patterns, "PRODUCT: Multispectral Imagery", name, size, ext)
            elif '_P001_PAN' in name:
                self._add_pattern(patterns, "PRODUCT: Panchromatic Imagery", name, size, ext)

            # Vivid basemap patterns
            if 'Vivid_Standard' in name:
                self._add_pattern(patterns, "PRODUCT: Vivid Standard Basemap", name, size, ext)

                # Extract region codes
                match = re.search(r'_([A-Z]{2}\d{2})_(\d{2}Q\d)', name)
                if match:
                    region = match.group(1)
                    quarter = match.group(2)
                    self._add_pattern(patterns, f"VIVID REGION: {region} ({quarter})", name, size, ext)

            # Folder structures
            if 'raster_tiles' in name:
                self._add_pattern(patterns, "STRUCTURE: Raster Tiles (tiled imagery)", name, size, ext)

            if any(x in name for x in ['tile_clouds', 'tile_geometries', 'tile_items']):
                self._add_pattern(patterns, "STRUCTURE: Tile Metadata", name, size, ext)

            if 'GIS_FILES' in name:
                self._add_pattern(patterns, "STRUCTURE: GIS Files (shapefiles)", name, size, ext)

        # Print patterns
        print("\n📁 FOLDER/FILE PATTERNS:")

        # Product types
        product_patterns = {k: v for k, v in patterns.items() if k.startswith("PRODUCT:")}
        if product_patterns:
            print("\n  📦 Product Types:")
            for key in sorted(product_patterns.keys()):
                p = product_patterns[key]
                print(f"    {key[9:]:40} {p['count']:>5} files | {p['size']/1024:>8.2f} GB")

        # Organizational patterns
        org_patterns = {k: v for k, v in patterns.items() if k.startswith("PATTERN:")}
        if org_patterns:
            print("\n  🏗️  Organizational Patterns:")
            for key in sorted(org_patterns.keys()):
                p = org_patterns[key]
                print(f"    {key[9:]:40} {p['count']:>5} files | {p['size']/1024:>8.2f} GB")

        # Folder structures
        struct_patterns = {k: v for k, v in patterns.items() if k.startswith("STRUCTURE:")}
        if struct_patterns:
            print("\n  📂 Folder Structures:")
            for key in sorted(struct_patterns.keys()):
                p = struct_patterns[key]
                print(f"    {key[11:]:40} {p['count']:>5} files | {p['size']/1024:>8.2f} GB")

        # Vivid regions
        vivid_patterns = {k: v for k, v in patterns.items() if k.startswith("VIVID REGION:")}
        if vivid_patterns:
            print("\n  🗺️  Vivid Basemap Regions:")
            for key in sorted(vivid_patterns.keys()):
                p = vivid_patterns[key]
                print(f"    {key[14:]:40} {p['count']:>5} files | {p['size']/1024:>8.2f} GB")

    def _add_pattern(self, patterns, key, name, size, ext):
        """Helper to add pattern match."""
        if key not in patterns:
            patterns[key] = {'count': 0, 'size': 0, 'examples': [], 'extensions': set()}

        patterns[key]['count'] += 1
        patterns[key]['size'] += size
        patterns[key]['extensions'].add(ext)

        if len(patterns[key]['examples']) < 3:
            patterns[key]['examples'].append(name)

    def analyze_duplicates(self, df: pd.DataFrame):
        """Identify potential duplicate files based on base filename."""
        stage2 = df[df['stage'] == 2].copy()

        if 'base_filename' not in stage2.columns or len(stage2) == 0:
            return

        # Find duplicates by base filename
        duplicates = stage2[stage2.duplicated(subset=['base_filename'], keep=False)]

        if len(duplicates) > 0:
            print(f"\n🔄 Potential Duplicates ({len(duplicates)} files):")
            print(f"  {len(duplicates['base_filename'].unique())} unique base filenames have duplicates")

            # Group by base filename and show examples
            dup_groups = duplicates.groupby('base_filename')
            print(f"\n  Top 5 duplicate groups:")
            for idx, (base_name, group) in enumerate(list(dup_groups)[:5]):
                print(f"\n  {idx+1}. '{base_name}' ({len(group)} copies):")
                for _, row in group.head(3).iterrows():
                    ext = row.get('file_extension', 'unknown')
                    size = row.get('size_mb', 0)
                    print(f"     - {ext:>12} | {size:>8.2f} MB | {row['blob_name'][:60]}")
                if len(group) > 3:
                    print(f"     ... and {len(group)-3} more")

            # Duplicate etags (exact binary duplicates)
            if 'etag' in duplicates.columns:
                exact_dups = duplicates[duplicates.duplicated(subset=['etag'], keep=False)]
                if len(exact_dups) > 0:
                    print(f"\n  ⚠️  Exact binary duplicates (same etag): {len(exact_dups)} files")
        else:
            print("\n🔄 Duplicates: None found")

    def print_summary(self, df: pd.DataFrame):
        """Print summary statistics."""
        print("\n" + "="*80)
        print("📊 TASK SUMMARY")
        print("="*80)

        print(f"\nTotal tasks: {len(df)}")

        # By stage
        print("\n🔢 Tasks by Stage:")
        print(df['stage'].value_counts().sort_index())

        # By status
        print("\n✅ Tasks by Status:")
        print(df['status'].value_counts())

        # By task type
        print("\n🔧 Tasks by Type:")
        print(df['task_type'].value_counts())

        # Stage 2 blob analysis
        stage2 = df[df['stage'] == 2]
        if len(stage2) > 0:
            print(f"\n📦 Stage 2 Blob Analysis ({len(stage2)} blobs):")

            # File categories
            if 'file_category' in stage2.columns:
                print("\n🗂️  File Categories:")
                categories = stage2['file_category'].value_counts()
                for category, count in categories.items():
                    cat_size = stage2[stage2['file_category'] == category]['size_mb'].sum()
                    print(f"  {category:>12}: {count:>5} files | {cat_size:>10.2f} MB ({cat_size/1024:>6.2f} GB)")

            # Vector files breakdown
            vector_files = stage2[stage2['file_category'] == 'vector']
            if len(vector_files) > 0:
                print(f"\n📐 Vector Files ({len(vector_files)} files, {vector_files['size_mb'].sum():.2f} MB):")
                print(vector_files['file_extension'].value_counts().head(10))

                # Identify complete shapefiles
                shp_files = vector_files[vector_files['file_extension'] == '.shp']
                if len(shp_files) > 0:
                    print(f"\n  Complete shapefiles: {len(shp_files)} (.shp files)")
                    # Check for complete shapefile sets (should have .dbf, .prj, .shx)
                    print(f"  Note: Each shapefile typically has 4+ components (.shp, .dbf, .prj, .shx)")

            # Raster files breakdown
            raster_files = stage2[stage2['file_category'] == 'raster']
            if len(raster_files) > 0:
                print(f"\n🗺️  Raster Files ({len(raster_files)} files, {raster_files['size_mb'].sum()/1024:.2f} GB):")
                print(raster_files['file_extension'].value_counts())
                print(f"\n  Largest rasters:")
                largest_rasters = raster_files.nlargest(5, 'size_mb')[['blob_name', 'size_mb', 'file_extension']]
                for _, row in largest_rasters.iterrows():
                    print(f"    {row['size_mb']:>10.2f} MB - {row['file_extension']:>6} - {row['blob_name'][:50]}")

            # Metadata files breakdown
            metadata_files = stage2[stage2['file_category'] == 'metadata']
            if len(metadata_files) > 0:
                print(f"\n📄 Metadata Files ({len(metadata_files)} files, {metadata_files['size_mb'].sum():.2f} MB):")
                print(metadata_files['file_extension'].value_counts().head(10))

            # File extensions
            if 'file_extension' in stage2.columns:
                print("\n📁 Top File Extensions:")
                print(stage2['file_extension'].value_counts().head(15))

            # Size distribution
            if 'size_mb' in stage2.columns:
                print("\n📏 Size Distribution (MB):")
                print(stage2['size_mb'].describe())
                print(f"  Total size: {stage2['size_mb'].sum():.2f} MB ({stage2['size_mb'].sum()/1024:.2f} GB)")

            # Folders vs files
            if 'is_folder' in stage2.columns:
                folders = stage2['is_folder'].sum()
                files = len(stage2) - folders
                print(f"\n📂 Folders: {folders}")
                print(f"📄 Files: {files}")

            # Largest files
            if 'size_mb' in stage2.columns and 'blob_name' in stage2.columns:
                print("\n🏆 Top 10 Largest Files:")
                largest = stage2.nlargest(10, 'size_mb')[['blob_name', 'size_mb', 'file_extension']]
                for idx, row in largest.iterrows():
                    print(f"  {row['size_mb']:>10.2f} MB - {row['file_extension']:>12} - {row['blob_name']}")

            # Folder pattern analysis
            self.analyze_folder_patterns(df)

            # Duplicates analysis
            self.analyze_duplicates(df)

        # Timing
        if 'created_at' in df.columns and 'updated_at' in df.columns:
            start = df['created_at'].min()
            end = df['updated_at'].max()
            duration = (end - start).total_seconds()

            print(f"\n⏱️  Execution Timing:")
            print(f"  Start: {start}")
            print(f"  End: {end}")
            print(f"  Duration: {duration:.2f} seconds ({duration/60:.2f} minutes)")

            if len(stage2) > 0:
                stage2_start = stage2['created_at'].min()
                stage2_end = stage2['updated_at'].max()
                stage2_duration = (stage2_end - stage2_start).total_seconds()
                print(f"  Stage 2 duration: {stage2_duration:.2f} seconds ({stage2_duration/60:.2f} minutes)")
                print(f"  Avg per blob: {stage2_duration/len(stage2):.2f} seconds")

        print("\n" + "="*80)

    def run(self, save_formats: Optional[List[str]] = None) -> pd.DataFrame:
        """Execute full analysis pipeline."""
        if save_formats is None:
            save_formats = ['csv', 'json']

        print(f"\n🚀 Starting analysis for job {self.job_id[:16]}...")
        print(f"📁 Output directory: {self.output_dir}\n")

        # Fetch data
        job_info = self.fetch_job_info()
        print(f"Job type: {job_info.get('jobType')}")
        print(f"Status: {job_info.get('status')}")
        print()

        tasks = self.fetch_all_tasks()

        # Convert to DataFrame
        df = self.tasks_to_dataframe(tasks)

        # Save outputs
        if 'json' in save_formats:
            self.save_raw_json(tasks)

        if 'csv' in save_formats:
            self.save_dataframe(df, format='csv')

        if 'parquet' in save_formats:
            self.save_dataframe(df, format='parquet')

        # Print summary
        self.print_summary(df)

        print(f"\n✅ Analysis complete! Files saved to: {self.output_dir}")

        return df


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python analyze_container_contents.py <job_id>")
        print("\nExample:")
        print("  python analyze_container_contents.py 8be5de7a789d0c9bb9c24c8d9e3dd313328b7690fbb8150e8e5082619be39b26")
        sys.exit(1)

    job_id = sys.argv[1]

    # Run analysis
    analyzer = ContainerContentsAnalyzer(job_id)
    df = analyzer.run(save_formats=['csv', 'json'])

    # Return DataFrame for interactive use
    return df


if __name__ == '__main__':
    df = main()
