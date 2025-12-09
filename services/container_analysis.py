"""
Container Analysis Service - Blob Container Analysis.

Analyzes list_container_contents job results to provide insights into:
    - File categorization (vector, raster, metadata)
    - Folder/organizational patterns
    - Duplicate detection
    - Size distribution and statistics

Design:
    - Pure Python (no pandas dependency)
    - Repository-based data access
    - Structured output for JSON serialization
    - Optional output to Blob Storage

Exports:
    analyze_container_job: Analyze a container listing job
    ContainerAnalysisService: Full analysis service class
"""

from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
import re
import json
from datetime import datetime, timezone
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ContainerAnalysis")


def analyze_container_job(job_id: str, save_to_blob: bool = False) -> Dict[str, Any]:
    """
    Analyze a list_container_contents job - convenience function.

    This is a helper function that creates a ContainerAnalysisService
    and runs the analysis. For HTTP endpoints or direct use.

    Args:
        job_id: Job ID to analyze
        save_to_blob: Whether to save results to blob storage

    Returns:
        Analysis results dict

    Example:
        # From HTTP trigger
        results = analyze_container_job('abc123...', save_to_blob=True)

        # From CLI
        results = analyze_container_job('abc123...', save_to_blob=False)
        print(json.dumps(results, indent=2))
    """
    from infrastructure import RepositoryFactory
    from infrastructure.blob import BlobRepository

    repos = RepositoryFactory.create_repositories()
    task_repo = repos['task_repo']

    # Create blob repository if saving requested
    # Analysis results are saved to silver zone (config.storage.silver.misc)
    blob_repo = None
    if save_to_blob:
        try:
            blob_repo = BlobRepository.for_zone("silver")  # Output to silver zone
            logger.info(f"✅ BlobRepository created for saving results (silver zone)")
        except Exception as e:
            logger.error(f"❌ Failed to create BlobRepository: {e}")
            # Continue without blob_repo - analysis will still work

    service = ContainerAnalysisService(task_repo, blob_repo)
    return service.analyze_job(job_id, save_output=save_to_blob)


class ContainerAnalysisService:
    """
    Analyze container contents job results.

    Pure service - no I/O side effects, returns structured data.
    Can be used from Azure Functions, batch jobs, or CLI tools.
    """

    def __init__(self, task_repository, blob_repository=None):
        """
        Initialize analysis service.

        Args:
            task_repository: ITaskRepository implementation for fetching tasks
            blob_repository: Optional IBlobRepository for saving results
        """
        self.task_repo = task_repository
        self.blob_repo = blob_repository

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def analyze_job(self, job_id: str, save_output: bool = False) -> Dict[str, Any]:
        """
        Analyze a list_container_contents job.

        Args:
            job_id: Job ID to analyze
            save_output: If True and blob_repo provided, save results to storage

        Returns:
            {
                'job_id': str,
                'analyzed_at': str (ISO timestamp),
                'summary': {
                    'total_files': int,
                    'total_size_gb': float,
                    'total_folders': int,
                    'execution_time_seconds': float
                },
                'file_categories': {
                    'vector': {'count': int, 'size_mb': float, 'extensions': {...}},
                    'raster': {'count': int, 'size_mb': float, 'extensions': {...}},
                    'metadata': {...},
                    'folder': {...},
                    'other': {...}
                },
                'patterns': {
                    'products': [...],
                    'organizations': [...],
                    'structures': [...],
                    'regions': [...]
                },
                'duplicates': {
                    'total_duplicate_files': int,
                    'unique_base_names': int,
                    'top_duplicates': [...]
                },
                'size_distribution': {
                    'buckets': {...},
                    'largest_files': [...]
                },
                'timing': {
                    'start': str,
                    'end': str,
                    'duration_seconds': float
                }
            }
        """
        # Fetch tasks from repository
        tasks = self._fetch_tasks(job_id)

        # Analyze
        results = self._analyze_tasks(tasks)

        # Add metadata
        results['job_id'] = job_id
        results['analyzed_at'] = datetime.utcnow().isoformat() + 'Z'

        # Optionally save to blob storage
        if save_output and self.blob_repo:
            self._save_results(job_id, results)

        return results

    def analyze_job_streaming(self, job_id: str) -> Dict[str, Any]:
        """
        Analyze job with streaming/chunked task fetching for large jobs.

        For jobs with 10,000+ tasks, fetch in batches to avoid memory issues.

        Args:
            job_id: Job ID to analyze

        Returns:
            Same structure as analyze_job()
        """
        # TODO: Implement chunked fetching for large jobs
        # For now, delegate to standard analysis
        return self.analyze_job(job_id)

    # =========================================================================
    # TASK FETCHING
    # =========================================================================

    def _fetch_tasks(self, job_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all tasks for a job from repository.

        Returns:
            List of task dicts with result_data
        """
        # Fetch tasks from repository
        task_records = self.task_repo.get_tasks_for_job(job_id)

        if not task_records:
            raise ValueError(f"No tasks found for job {job_id}")

        # Convert TaskRecord objects to dicts
        return [task.model_dump() for task in task_records]

    # =========================================================================
    # CORE ANALYSIS
    # =========================================================================

    def _analyze_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Core analysis logic - processes task list into structured insights.

        Args:
            tasks: List of task dicts from database

        Returns:
            Analysis results dict
        """
        # Separate Stage 1 (list) and Stage 2 (analyze) tasks
        # Handle both 'stage' and 'stage_number' field names
        stage2_tasks = [
            t for t in tasks
            if t.get('stage') == 2 or t.get('stage_number') == 2
        ]

        # Extract blob data from tasks
        blobs = self._extract_blob_data(stage2_tasks)

        # Run all analysis components
        return {
            'summary': self._create_summary(blobs, tasks),
            'file_categories': self._categorize_files(blobs),
            'patterns': self._detect_patterns(blobs),
            'duplicates': self._find_duplicates(blobs),
            'size_distribution': self._analyze_size_distribution(blobs),
            'timing': self._extract_timing(tasks)
        }

    # =========================================================================
    # BLOB DATA EXTRACTION
    # =========================================================================

    def _extract_blob_data(self, stage2_tasks: List[Dict]) -> List[Dict[str, Any]]:
        """
        Extract blob information from Stage 2 tasks.

        Args:
            stage2_tasks: List of analyze_single_blob task results

        Returns:
            List of blob info dicts:
            [
                {
                    'name': str,
                    'path': str,
                    'size_mb': float,
                    'size_bytes': int,
                    'extension': str,
                    'content_type': str,
                    'is_folder': bool,
                    'last_modified': str,
                    'etag': str,
                    'base_filename': str
                },
                ...
            ]
        """
        blobs = []

        for task in stage2_tasks:
            result = task.get('result_data', {}).get('result', {})

            if not result:
                continue

            blob_name = result.get('blob_name', '')
            file_ext = result.get('file_extension', '')

            # Extract base filename for duplicate detection
            base_name = self._extract_base_filename(blob_name, file_ext)

            blobs.append({
                'name': blob_name,
                'path': result.get('blob_path', ''),
                'size_mb': result.get('size_mb', 0),
                'size_bytes': result.get('size_bytes', 0),
                'extension': file_ext,
                'content_type': result.get('content_type'),
                'is_folder': result.get('metadata', {}).get('hdi_isfolder') == 'true',
                'last_modified': result.get('last_modified'),
                'etag': result.get('etag'),
                'base_filename': base_name
            })

        return blobs

    def _extract_base_filename(self, blob_name: str, extension: str) -> str:
        """Extract base filename without path and extension."""
        # Remove path
        if '/' in blob_name:
            base = blob_name.split('/')[-1]
        else:
            base = blob_name

        # Remove extension
        if '.' in base and extension != 'no_extension':
            base = base.rsplit('.', 1)[0]

        return base

    # =========================================================================
    # FILE CATEGORIZATION
    # =========================================================================

    def _categorize_files(self, blobs: List[Dict]) -> Dict[str, Any]:
        """
        Categorize files into vector, raster, metadata, folder, other.

        Returns:
            {
                'vector': {
                    'count': int,
                    'size_mb': float,
                    'extensions': {'ext': count, ...}
                },
                'raster': {...},
                'metadata': {...},
                'folder': {...},
                'other': {...}
            }
        """
        categories = defaultdict(lambda: {
            'count': 0,
            'size_mb': 0,
            'extensions': defaultdict(int)
        })

        for blob in blobs:
            category = self._categorize_blob(blob['extension'], blob['name'])

            categories[category]['count'] += 1
            categories[category]['size_mb'] += blob['size_mb']
            categories[category]['extensions'][blob['extension']] += 1

        # Convert defaultdicts to regular dicts for JSON serialization
        return {
            cat: {
                'count': data['count'],
                'size_mb': data['size_mb'],
                'extensions': dict(data['extensions'])
            }
            for cat, data in categories.items()
        }

    def _categorize_blob(self, extension: str, name: str) -> str:
        """Categorize single blob into category."""
        ext_lower = extension.lower()

        # Vector formats
        if ext_lower in {'.shp', '.dbf', '.prj', '.shx', '.geojson', '.json', '.kml', '.gpkg', '.gdb'}:
            return 'vector'

        # Raster formats
        if ext_lower in {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.bmp'}:
            return 'raster'

        # Metadata/documentation
        if ext_lower in {'.xml', '.txt', '.md', '.imd', '.rpb', '.til', '.man'} or 'readme' in name.lower():
            return 'metadata'

        # Folders
        if ext_lower == 'no_extension':
            return 'folder'

        return 'other'

    # =========================================================================
    # PATTERN DETECTION
    # =========================================================================

    def _detect_patterns(self, blobs: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Detect organizational patterns (Maxar, Vivid, etc.).

        Returns:
            {
                'products': [
                    {'name': str, 'count': int, 'size_mb': float},
                    ...
                ],
                'organizations': [...],
                'structures': [...],
                'regions': [...]
            }
        """
        patterns = defaultdict(lambda: {'count': 0, 'size_mb': 0})

        for blob in blobs:
            name = blob['name']
            size = blob['size_mb']

            if '/' not in name:
                continue

            parts = name.split('/')
            top = parts[0]

            # Detect patterns
            self._detect_maxar_pattern(patterns, top, name, size)
            self._detect_vivid_pattern(patterns, top, name, size)
            self._detect_product_type(patterns, name, size)
            self._detect_structure_type(patterns, name, size)

        # Format for output
        return {
            'products': self._format_patterns(patterns, 'PRODUCT:'),
            'organizations': self._format_patterns(patterns, 'PATTERN:'),
            'structures': self._format_patterns(patterns, 'STRUCTURE:'),
            'regions': self._format_patterns(patterns, 'VIVID_REGION:')
        }

    def _detect_maxar_pattern(self, patterns: Dict, top: str, name: str, size: float):
        """Detect Maxar order patterns."""
        # Maxar order: numeric GUID folder
        if top.isdigit() and len(top) > 15:
            patterns['PATTERN:Maxar Order']['count'] += 1
            patterns['PATTERN:Maxar Order']['size_mb'] += size

    def _detect_vivid_pattern(self, patterns: Dict, top: str, name: str, size: float):
        """Detect Vivid basemap patterns."""
        # Vivid: UUID folder
        if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', top):
            patterns['PATTERN:Vivid Basemap']['count'] += 1
            patterns['PATTERN:Vivid Basemap']['size_mb'] += size

        # Vivid regions
        if 'Vivid_Standard' in name:
            match = re.search(r'_([A-Z]{2}\d{2})_(\d{2}Q\d)', name)
            if match:
                region = f"{match.group(1)} ({match.group(2)})"
                patterns[f'VIVID_REGION:{region}']['count'] += 1
                patterns[f'VIVID_REGION:{region}']['size_mb'] += size

    def _detect_product_type(self, patterns: Dict, name: str, size: float):
        """Detect product types (Pansharpened, Multispectral, etc.)."""
        if '_P001_PSH' in name:
            patterns['PRODUCT:Pansharpened Imagery']['count'] += 1
            patterns['PRODUCT:Pansharpened Imagery']['size_mb'] += size
        elif '_P001_MUL' in name:
            patterns['PRODUCT:Multispectral Imagery']['count'] += 1
            patterns['PRODUCT:Multispectral Imagery']['size_mb'] += size
        elif '_P001_PAN' in name:
            patterns['PRODUCT:Panchromatic Imagery']['count'] += 1
            patterns['PRODUCT:Panchromatic Imagery']['size_mb'] += size

        if 'Vivid_Standard' in name:
            patterns['PRODUCT:Vivid Standard Basemap']['count'] += 1
            patterns['PRODUCT:Vivid Standard Basemap']['size_mb'] += size

    def _detect_structure_type(self, patterns: Dict, name: str, size: float):
        """Detect folder structure types."""
        if 'raster_tiles' in name:
            patterns['STRUCTURE:Raster Tiles']['count'] += 1
            patterns['STRUCTURE:Raster Tiles']['size_mb'] += size

        if any(x in name for x in ['tile_clouds', 'tile_geometries', 'tile_items']):
            patterns['STRUCTURE:Tile Metadata']['count'] += 1
            patterns['STRUCTURE:Tile Metadata']['size_mb'] += size

        if 'GIS_FILES' in name:
            patterns['STRUCTURE:GIS Files']['count'] += 1
            patterns['STRUCTURE:GIS Files']['size_mb'] += size

    def _format_patterns(self, patterns: Dict, prefix: str) -> List[Dict]:
        """Format pattern dict for output."""
        result = []
        for key, data in patterns.items():
            if key.startswith(prefix):
                result.append({
                    'name': key.replace(prefix, ''),
                    'count': data['count'],
                    'size_mb': data['size_mb'],
                    'size_gb': data['size_mb'] / 1024
                })

        return sorted(result, key=lambda x: x['size_mb'], reverse=True)

    # =========================================================================
    # DUPLICATE DETECTION
    # =========================================================================

    def _find_duplicates(self, blobs: List[Dict]) -> Dict[str, Any]:
        """
        Find duplicate files by base filename.

        Returns:
            {
                'total_duplicate_files': int,
                'unique_base_names': int,
                'top_duplicates': [
                    {
                        'base_name': str,
                        'count': int,
                        'total_size_mb': float,
                        'examples': [...]
                    },
                    ...
                ]
            }
        """
        # Group by base filename
        by_basename = defaultdict(list)
        for blob in blobs:
            by_basename[blob['base_filename']].append(blob)

        # Find duplicates (2+ files with same base name)
        duplicates = {k: v for k, v in by_basename.items() if len(v) > 1}

        # Format top duplicates
        top_dups = []
        for base_name, blob_list in sorted(duplicates.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            top_dups.append({
                'base_name': base_name,
                'count': len(blob_list),
                'total_size_mb': sum(b['size_mb'] for b in blob_list),
                'examples': [
                    {
                        'name': b['name'],
                        'extension': b['extension'],
                        'size_mb': b['size_mb']
                    }
                    for b in blob_list[:5]  # First 5 examples
                ]
            })

        return {
            'total_duplicate_files': sum(len(v) for v in duplicates.values()),
            'unique_base_names': len(duplicates),
            'top_duplicates': top_dups
        }

    # =========================================================================
    # SIZE DISTRIBUTION
    # =========================================================================

    def _analyze_size_distribution(self, blobs: List[Dict]) -> Dict[str, Any]:
        """
        Analyze file size distribution.

        Returns:
            {
                'buckets': {
                    '0-10MB': int,
                    '10-100MB': int,
                    ...
                },
                'largest_files': [...]
            }
        """
        buckets = {
            '0-10MB': 0,
            '10-100MB': 0,
            '100MB-1GB': 0,
            '1GB-10GB': 0,
            '10GB+': 0
        }

        for blob in blobs:
            size_mb = blob['size_mb']

            if size_mb < 10:
                buckets['0-10MB'] += 1
            elif size_mb < 100:
                buckets['10-100MB'] += 1
            elif size_mb < 1024:
                buckets['100MB-1GB'] += 1
            elif size_mb < 10240:
                buckets['1GB-10GB'] += 1
            else:
                buckets['10GB+'] += 1

        # Largest files
        largest = sorted(blobs, key=lambda x: x['size_mb'], reverse=True)[:10]

        return {
            'buckets': buckets,
            'largest_files': [
                {
                    'name': b['name'],
                    'size_mb': b['size_mb'],
                    'size_gb': b['size_mb'] / 1024,
                    'extension': b['extension']
                }
                for b in largest
            ]
        }

    # =========================================================================
    # SUMMARY & TIMING
    # =========================================================================

    def _create_summary(self, blobs: List[Dict], all_tasks: List[Dict]) -> Dict[str, Any]:
        """Create summary statistics."""
        files = [b for b in blobs if not b['is_folder']]
        folders = [b for b in blobs if b['is_folder']]

        total_size_mb = sum(b['size_mb'] for b in files)

        return {
            'total_files': len(files),
            'total_folders': len(folders),
            'total_size_mb': total_size_mb,
            'total_size_gb': total_size_mb / 1024,
            'total_tasks': len(all_tasks),
            'stage2_tasks': len(blobs)
        }

    def _extract_timing(self, tasks: List[Dict]) -> Dict[str, Any]:
        """Extract timing information from tasks."""
        if not tasks:
            return {}

        # Parse timestamps - handle both string and datetime objects
        created = []
        updated = []

        for t in tasks:
            # Handle created_at
            created_at = t.get('created_at')
            if isinstance(created_at, str):
                created.append(datetime.fromisoformat(created_at.replace('Z', '+00:00')))
            elif isinstance(created_at, datetime):
                created.append(created_at)

            # Handle updated_at
            updated_at = t.get('updated_at')
            if isinstance(updated_at, str):
                updated.append(datetime.fromisoformat(updated_at.replace('Z', '+00:00')))
            elif isinstance(updated_at, datetime):
                updated.append(updated_at)

        if not created or not updated:
            return {}

        start = min(created)
        end = max(updated)
        duration = (end - start).total_seconds()

        return {
            'start': start.isoformat(),
            'end': end.isoformat(),
            'duration_seconds': duration,
            'duration_minutes': duration / 60
        }

    # =========================================================================
    # OUTPUT PERSISTENCE
    # =========================================================================

    def _save_results(self, job_id: str, results: Dict[str, Any]):
        """
        Save analysis results to Blob Storage or ADLS.

        Output Locations:
        - Azure Blob Storage: container 'analysis-results'
        - Path: analysis-results/container-analysis/{job_id}/{timestamp}.json
        - Optionally: ADLS Gen2 path for data lake integration

        Args:
            job_id: Job ID being analyzed
            results: Analysis results dict
        """
        if not self.blob_repo:
            logger.warning("Blob repository not available - skipping save")
            results['output'] = {
                'saved': False,
                'error': 'Blob repository not initialized'
            }
            return

        import json

        # Generate output path
        from config import get_config
        config = get_config()
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        # Use silver misc container for analysis output
        container = config.storage.silver.misc
        blob_path = f"container-analysis/{job_id}/{timestamp}.json"

        # Serialize to JSON
        json_content = json.dumps(results, indent=2, default=str)

        # Write to blob storage
        try:
            self.blob_repo.write_blob(
                container=container,
                blob_path=blob_path,
                data=json_content.encode('utf-8'),
                overwrite=True,
                content_type='application/json',
                metadata={'job_id': job_id, 'analysis_type': 'container_analysis'}
            )

            # Add output location to results
            results['output'] = {
                'saved': True,
                'container': container,
                'blob_path': blob_path,
                'timestamp': timestamp
            }
        except Exception as e:
            # Log error but don't fail the analysis
            logger.warning(f"Failed to save results to blob storage: {e}")
            results['output'] = {
                'saved': False,
                'error': str(e)
            }
