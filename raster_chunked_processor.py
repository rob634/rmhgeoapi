"""
Chunked Raster Processor - Processes large rasters using unlimited blob storage
Breaks large operations into small chunks, storing everything in blob storage
"""
import json
import os
import tempfile
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from logger_setup import logger
from base_raster_processor import BaseRasterProcessor


class ChunkedRasterProcessor(BaseRasterProcessor):
    """
    Processes massive rasters by chunking them into tiles stored in blob storage
    No size limits - uses blob storage liberally for all intermediate results
    """
    
    # Processing configuration
    CHUNK_SIZE = 10000  # Process in 10000x10000 pixel chunks (much larger to reduce chunk count)
    MAX_MEMORY_MB = 500  # Keep memory usage under 500MB per chunk
    
    def __init__(self):
        """Initialize chunked processor with base functionality"""
        super().__init__()
        from config import Config
        
        # Additional configuration specific to chunked processing
        self.state_container = Config.STATE_CONTAINER_NAME
        self.use_adls = Config.USE_ADLS
        
        # Note: Container and folder configuration inherited from base class
        # self.silver_container, self.temp_folder, self.cogs_folder, self.chunks_folder
        
        self._init_storage()
    
    def _generate_mosaic_output_name(self, input_files: List[str], custom_name: str = None) -> str:
        """
        Generate a smart output name for mosaics
        - Removes row/column suffixes like _R1C1, _R2C2
        - Adds timestamp and mosaic identifier
        - Uses custom name if provided
        """
        import re
        from datetime import datetime
        
        if custom_name and custom_name != "mosaic_output" and custom_name != "namangan_mosaic_test":
            # Use custom name if provided and not default
            if not custom_name.endswith('.tif'):
                custom_name += '.tif'
            return custom_name
        
        # Extract base name from first file
        if input_files:
            first_file = input_files[0]
            # Get just the filename without path
            base_name = first_file.split('/')[-1]
            
            # Remove extension
            if base_name.endswith('.tif'):
                base_name = base_name[:-4]
            
            # Remove common tile suffixes
            # Pattern matches _R{digit}C{digit} or similar row/column patterns
            base_name = re.sub(r'[_-]?R\d+C\d+', '', base_name)
            base_name = re.sub(r'[_-]?r\d+c\d+', '', base_name)
            base_name = re.sub(r'[_-]?row\d+[_-]?col\d+', '', base_name, flags=re.IGNORECASE)
            base_name = re.sub(r'[_-]?tile[_-]?\d+[_-]?\d+', '', base_name, flags=re.IGNORECASE)
            
            # Remove 'cog' suffix if present (will be added back)
            base_name = re.sub(r'[_-]?cog$', '', base_name, flags=re.IGNORECASE)
            
            # Add mosaic identifier
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            tile_count = len(input_files)
            
            if tile_count > 1:
                output_name = f"{base_name}_mosaic_{tile_count}tiles_{timestamp}_cog.tif"
            else:
                output_name = f"{base_name}_{timestamp}_cog.tif"
        else:
            # Fallback
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_name = f"mosaic_{timestamp}_cog.tif"
        
        return output_name
    
    def _init_storage(self):
        """Initialize storage and ensure containers exist"""
        # Use blob_service from base class storage repository
        self.blob_service = self.storage.blob_service
        
        # If using ADLS, initialize DataLake client as well
        if self.use_adls:
            from azure.storage.filedatalake import DataLakeServiceClient
            datalake_url = account_url.replace('.blob.', '.dfs.')
            self.datalake_service = DataLakeServiceClient(datalake_url, credential=DefaultAzureCredential())
        else:
            self.datalake_service = None
        
        # Ensure silver container exists
        try:
            container_client = self.blob_service.get_container_client(self.silver_container)
            if not container_client.exists():
                container_client.create_container()
                logger.info(f"Created container: {self.silver_container}")
        except Exception as e:
            logger.warning(f"Container {self.silver_container} may already exist: {e}")
        
        # Note: Folders don't need to be explicitly created in blob storage
        # They are virtual and created when first blob is uploaded
        
        # Ensure state container exists (keep separate for management)
        try:
            state_container_client = self.blob_service.get_container_client(self.state_container)
            if not state_container_client.exists():
                state_container_client.create_container()
                logger.info(f"Created state container: {self.state_container}")
        except Exception as e:
            logger.warning(f"State container may already exist: {e}")
    
    def start_chunked_mosaic(self, job_id: str, input_files: List[str], 
                             source_container: str, output_name: str, 
                             target_crs: str = "EPSG:4326") -> Dict:
        """
        Start a chunked mosaic operation that can handle ANY size
        
        Strategy:
        1. Create a virtual grid covering all inputs
        2. Process each grid cell independently
        3. Store each processed chunk in blob
        4. Final assembly reads chunks from blob
        """
        try:
            logger.info(f"Starting chunked mosaic for {len(input_files)} files from {source_container}")
            
            # Generate SAS URLs for input files using base class method
            input_urls = []
            for file_name in input_files:
                try:
                    # Use base class method for URL generation
                    file_url = self.get_blob_url(source_container, file_name)
                    input_urls.append(file_url)
                except Exception as e:
                    logger.error(f"Failed to get SAS URL for {file_name}: {e}")
                    raise ValueError(f"Cannot access input file {file_name}: {e}")
            
            # Step 1: Analyze all inputs and determine output grid
            analysis = self._analyze_inputs(input_urls, target_crs)
            
            # Step 2: Create processing plan
            grid_plan = self._create_grid_plan(analysis)
            
            # Generate smart output name
            smart_output_name = self._generate_mosaic_output_name(input_files, output_name)
            logger.info(f"Generated output name: {smart_output_name}")
            
            # Step 3: Initialize job state
            job_state = {
                "job_id": job_id,
                "operation": "chunked_mosaic",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "initialized",
                "inputs": input_urls,  # Store URLs for processing
                "input_files": input_files,  # Store original file names for reference
                "source_container": source_container,
                "output_name": smart_output_name,  # Use smart name
                "target_crs": target_crs,
                "analysis": analysis,
                "grid": grid_plan,
                "chunks_completed": [],
                "chunks_pending": list(range(grid_plan['total_chunks'])),
                "chunk_urls": {},  # Maps chunk_id to blob URL
                "progress": {
                    "total_chunks": grid_plan['total_chunks'],
                    "completed_chunks": 0,
                    "percent_complete": 0
                }
            }
            
            # Save initial state
            self._save_state(job_id, job_state)
            
            # Queue first chunk
            self._queue_chunk(job_id, 0)
            
            logger.info(f"Chunked mosaic initialized: {grid_plan['total_chunks']} chunks to process")
            return job_state
            
        except Exception as e:
            logger.error(f"Error starting chunked mosaic: {e}")
            raise
    
    def process_chunk(self, job_id: str, chunk_id: int) -> Dict:
        """
        Process a single chunk of the mosaic
        Each chunk is independent and can be processed in parallel if needed
        """
        try:
            # Load job state
            job_state = self._load_state(job_id)
            
            if chunk_id in job_state['chunks_completed']:
                logger.info(f"Chunk {chunk_id} already completed")
                return job_state
            
            logger.info(f"Processing chunk {chunk_id}/{job_state['grid']['total_chunks']}")
            
            # Get chunk window
            chunk_window = self._get_chunk_window(job_state['grid'], chunk_id)
            
            # Process this chunk from all inputs
            chunk_data = self._process_chunk_from_inputs(
                job_state['inputs'],
                chunk_window,
                job_state['target_crs'],
                job_state['analysis']['output_profile']
            )
            
            # Store chunk in blob storage
            chunk_url = self._store_chunk(job_id, chunk_id, chunk_data, 
                                         job_state['analysis']['output_profile'])
            
            # Update state
            job_state['chunks_completed'].append(chunk_id)
            job_state['chunks_pending'].remove(chunk_id)
            job_state['chunk_urls'][str(chunk_id)] = chunk_url
            job_state['progress']['completed_chunks'] += 1
            job_state['progress']['percent_complete'] = int(
                (job_state['progress']['completed_chunks'] / 
                 job_state['progress']['total_chunks']) * 100
            )
            
            # Check if all chunks are done
            if len(job_state['chunks_pending']) == 0:
                job_state['status'] = 'assembling'
                logger.info(f"All chunks complete for {job_id}, ready for assembly")
                # Queue assembly job
                self._queue_assembly(job_id)
            else:
                # Queue next chunk(s) - can queue multiple for parallel processing
                next_chunks = job_state['chunks_pending'][:3]  # Process up to 3 chunks in parallel
                for next_chunk in next_chunks:
                    self._queue_chunk(job_id, next_chunk)
            
            # Save updated state
            self._save_state(job_id, job_state)
            
            return job_state
            
        except Exception as e:
            logger.error(f"Error processing chunk {chunk_id}: {e}")
            raise
    
    def assemble_chunks(self, job_id: str) -> Dict:
        """
        Assemble all chunks into final mosaic
        Reads chunks from blob storage and creates final COG
        """
        try:
            job_state = self._load_state(job_id)
            
            logger.info(f"Assembling {len(job_state['chunks_completed'])} chunks into final mosaic")
            
            # Create output profile
            profile = job_state['analysis']['output_profile']
            
            # Convert transform back from list if needed
            from rasterio.transform import Affine
            if isinstance(profile['transform'], (list, tuple)):
                profile['transform'] = Affine(*profile['transform'])
            
            # Create temporary file for assembly
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
                temp_output = tmp.name
            
            # Write assembled mosaic
            with rasterio.open(temp_output, 'w', **profile) as dst:
                # Process each chunk
                for chunk_id in range(job_state['grid']['total_chunks']):
                    logger.info(f"Writing chunk {chunk_id} to mosaic")
                    
                    # Get chunk window
                    chunk_window = self._get_chunk_window(job_state['grid'], chunk_id)
                    
                    # Download chunk from blob
                    chunk_data = self._download_chunk(job_state['chunk_urls'][str(chunk_id)])
                    
                    # Write to output - handle multi-band data
                    if chunk_data.ndim == 3:
                        # Multi-band: write each band separately
                        for band_idx in range(chunk_data.shape[0]):
                            dst.write(chunk_data[band_idx], band_idx + 1, window=chunk_window)
                    else:
                        # Single band
                        dst.write(chunk_data, 1, window=chunk_window)
                
                # Add overviews for COG
                logger.info("Building overviews for COG")
                factors = [2, 4, 8, 16, 32]
                dst.build_overviews(factors, Resampling.average)
                dst.update_tags(ns='rio_overview', resampling='average')
            
            # Upload final mosaic to blob storage
            final_url = self._upload_final_mosaic(job_id, temp_output, job_state['output_name'])
            
            # Clean up temp file
            os.remove(temp_output)
            
            # Update state
            job_state['status'] = 'completed'
            job_state['output_url'] = final_url
            job_state['completed_at'] = datetime.now(timezone.utc).isoformat()
            
            # Clean up chunks (optional - might want to keep for a while)
            self._cleanup_chunks(job_id, job_state['chunk_urls'])
            
            self._save_state(job_id, job_state)
            
            logger.info(f"Mosaic assembly complete: {final_url}")
            return job_state
            
        except Exception as e:
            logger.error(f"Error assembling chunks: {e}")
            raise
    
    def _analyze_inputs(self, input_files: List[str], target_crs: str) -> Dict:
        """
        Analyze all input files to determine output characteristics
        """
        logger.info(f"Analyzing {len(input_files)} input files")
        
        # Collect bounds and metadata from all inputs
        all_bounds = []
        resolutions = []
        count = None
        dtype = None
        
        for file_url in input_files:
            with rasterio.open(file_url) as src:
                # Transform bounds to target CRS if needed
                if str(src.crs) != target_crs:
                    bounds = rasterio.warp.transform_bounds(
                        src.crs, target_crs, *src.bounds
                    )
                else:
                    bounds = src.bounds
                
                all_bounds.append(bounds)
                resolutions.append(src.res[0])  # Assume square pixels
                
                if count is None:
                    count = src.count
                    dtype = src.dtypes[0]
        
        # Calculate overall bounds
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)
        
        output_bounds = (min_x, min_y, max_x, max_y)
        
        # Use finest resolution
        output_res = min(resolutions)
        
        # Calculate output dimensions
        width = int((max_x - min_x) / output_res)
        height = int((max_y - min_y) / output_res)
        
        # Create output transform
        from rasterio.transform import from_bounds
        transform = from_bounds(min_x, min_y, max_x, max_y, width, height)
        
        return {
            "bounds": output_bounds,
            "resolution": output_res,
            "width": width,
            "height": height,
            "count": count,
            "dtype": dtype,
            "output_profile": {
                "driver": "GTiff",
                "width": width,
                "height": height,
                "count": count,
                "dtype": dtype,
                "crs": target_crs,
                "transform": list(transform),  # Convert to list for JSON serialization
                "compress": "lzw",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512
            }
        }
    
    def _create_grid_plan(self, analysis: Dict) -> Dict:
        """
        Create a grid plan for chunked processing
        """
        width = analysis['width']
        height = analysis['height']
        
        # Calculate number of chunks
        chunks_x = (width + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
        chunks_y = (height + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
        
        total_chunks = chunks_x * chunks_y
        
        logger.info(f"Grid plan: {chunks_x}x{chunks_y} = {total_chunks} chunks")
        
        return {
            "chunks_x": chunks_x,
            "chunks_y": chunks_y,
            "total_chunks": total_chunks,
            "chunk_size": self.CHUNK_SIZE,
            "width": width,
            "height": height
        }
    
    def _get_chunk_window(self, grid: Dict, chunk_id: int) -> Window:
        """
        Get the window for a specific chunk
        """
        chunks_x = grid['chunks_x']
        chunk_y = chunk_id // chunks_x
        chunk_x = chunk_id % chunks_x
        
        col_off = chunk_x * self.CHUNK_SIZE
        row_off = chunk_y * self.CHUNK_SIZE
        
        width = min(self.CHUNK_SIZE, grid['width'] - col_off)
        height = min(self.CHUNK_SIZE, grid['height'] - row_off)
        
        return Window(col_off, row_off, width, height)
    
    def _process_chunk_from_inputs(self, input_files: List[str], window: Window,
                                   target_crs: str, output_profile: Dict) -> np.ndarray:
        """
        Process a chunk from all input files
        """
        # Calculate bounds for this window
        # Convert transform back from list if needed
        from rasterio.transform import Affine
        transform = output_profile['transform']
        if isinstance(transform, (list, tuple)):
            transform = Affine(*transform)
        chunk_bounds = rasterio.windows.bounds(window, transform)
        
        # Collect data from all inputs for this chunk
        chunk_datasets = []
        
        for file_url in input_files:
            with rasterio.open(file_url) as src:
                # Calculate window in source that overlaps with our chunk
                if str(src.crs) != target_crs:
                    # Need to reproject
                    # This is more complex - for now simplified
                    pass
                else:
                    # Calculate source window that overlaps
                    src_window = rasterio.windows.from_bounds(
                        *chunk_bounds, transform=src.transform
                    )
                    
                    # Read data for this window
                    try:
                        data = src.read(window=src_window)
                        chunk_datasets.append(data)
                    except:
                        # No overlap
                        pass
        
        # Merge all data for this chunk (simplified - needs proper merge logic)
        if chunk_datasets:
            # Ensure all arrays have the same shape before merging
            # Get the expected shape
            expected_shape = (output_profile['count'], window.height, window.width)
            
            # Resize/pad arrays to match expected shape if needed
            resized_datasets = []
            for data in chunk_datasets:
                if data.shape != expected_shape:
                    # Create output array with expected shape
                    resized = np.zeros(expected_shape, dtype=data.dtype)
                    # Copy data (handle different band counts)
                    min_bands = min(data.shape[0], expected_shape[0])
                    min_height = min(data.shape[1] if data.ndim > 1 else 1, expected_shape[1])
                    min_width = min(data.shape[2] if data.ndim > 2 else 1, expected_shape[2])
                    resized[:min_bands, :min_height, :min_width] = data[:min_bands, :min_height, :min_width]
                    resized_datasets.append(resized)
                else:
                    resized_datasets.append(data)
            
            # Use maximum value for overlaps (or could use mean, first, etc.)
            merged = np.maximum.reduce(resized_datasets)
            return merged
        else:
            # Return empty chunk
            return np.zeros((output_profile['count'], 
                           window.height, window.width), 
                          dtype=output_profile['dtype'])
    
    def _store_chunk(self, job_id: str, chunk_id: int, 
                    chunk_data: np.ndarray, profile: Dict) -> str:
        """
        Store a chunk in blob storage using folder structure
        """
        # Create chunk blob path in chunks folder within silver container
        chunk_blob = f"{self.chunks_folder}/{job_id}/chunk_{chunk_id:06d}.npy"
        
        # Save as numpy array (efficient for numerical data)
        with tempfile.NamedTemporaryFile(suffix='.npy', delete=False) as tmp:
            np.save(tmp.name, chunk_data)
            tmp_path = tmp.name
        
        # Upload to blob in silver container with folder path
        blob_client = self.blob_service.get_blob_client(
            container=self.silver_container,
            blob=chunk_blob
        )
        
        with open(tmp_path, 'rb') as data:
            blob_client.upload_blob(data, overwrite=True)
        
        os.remove(tmp_path)
        
        return blob_client.url
    
    def _download_chunk(self, chunk_url: str) -> np.ndarray:
        """
        Download a chunk from blob storage
        """
        # Extract blob path from URL (chunks are in silver container)
        # URL format: https://account.blob.core.windows.net/container/chunks/job_id/chunk_000000.npy
        if '/chunks/' in chunk_url:
            blob_name = chunk_url.split('/chunks/')[-1]
            blob_name = f"{self.chunks_folder}/{blob_name}"
        else:
            # Fallback to extracting from URL
            parts = chunk_url.split('/')
            blob_name = '/'.join(parts[-3:])  # Get folder/job_id/chunk.npy
        
        blob_client = self.blob_service.get_blob_client(
            container=self.silver_container,
            blob=blob_name
        )
        
        # Download to temp file
        with tempfile.NamedTemporaryFile(suffix='.npy', delete=False) as tmp:
            download_stream = blob_client.download_blob()
            download_stream.readinto(tmp)
            tmp_path = tmp.name
        
        # Load numpy array
        data = np.load(tmp_path)
        os.remove(tmp_path)
        
        return data
    
    def _move_or_rename_blob(self, source_container: str, source_path: str, 
                            dest_container: str, dest_path: str) -> bool:
        """
        Efficiently move or rename a blob using ADLS if available
        Falls back to copy+delete for standard blob storage
        """
        try:
            if self.use_adls and self.datalake_service:
                # Use ADLS for metadata-only rename/move operation
                logger.info(f"Using ADLS to move {source_path} to {dest_path}")
                
                source_fs = self.datalake_service.get_file_system_client(source_container)
                source_file = source_fs.get_file_client(source_path)
                
                # If different container, need to copy then delete
                if source_container != dest_container:
                    dest_fs = self.datalake_service.get_file_system_client(dest_container)
                    dest_file = dest_fs.get_file_client(dest_path)
                    
                    # Copy to new location
                    dest_file.create_file()
                    dest_file.append_data(source_file.read_file(), 0)
                    source_file.delete_file()
                else:
                    # Same container - can rename (metadata-only operation)
                    source_file.rename_file(f"{dest_container}/{dest_path}")
                
                logger.info(f"Successfully moved file using ADLS")
                return True
            else:
                # Fallback to standard blob copy+delete
                logger.info(f"Using standard blob copy to move {source_path} to {dest_path}")
                
                source_blob = self.blob_service.get_blob_client(source_container, source_path)
                dest_blob = self.blob_service.get_blob_client(dest_container, dest_path)
                
                # Copy blob
                dest_blob.start_copy_from_url(source_blob.url)
                
                # Wait for copy to complete then delete source
                import time
                max_wait = 60
                waited = 0
                while waited < max_wait:
                    props = dest_blob.get_blob_properties()
                    if props.copy.status == 'success':
                        source_blob.delete_blob()
                        logger.info("Successfully copied and deleted source")
                        return True
                    time.sleep(1)
                    waited += 1
                
                logger.warning("Copy operation timed out")
                return False
                
        except Exception as e:
            logger.error(f"Error moving/renaming blob: {e}")
            return False
    
    def _upload_final_mosaic(self, job_id: str, local_path: str, output_name: str) -> str:
        """
        Upload final mosaic to Silver container using efficient rename from temp
        """
        # First upload to temp folder
        temp_blob_name = f"{self.temp_folder}/{job_id}/{output_name}"
        
        # Upload to temp location
        temp_blob_client = self.blob_service.get_blob_client(
            container=self.silver_container,
            blob=temp_blob_name
        )
        
        with open(local_path, 'rb') as data:
            temp_blob_client.upload_blob(data, overwrite=True)
        
        logger.info(f"Uploaded to temp: {temp_blob_name}")
        
        # Now rename from temp to final location (cogs folder)
        final_blob_name = f"{self.cogs_folder}/{output_name}"
        
        # Use efficient rename if possible
        success = self._move_or_rename_blob(
            source_container=self.silver_container,
            source_path=temp_blob_name,
            dest_container=self.silver_container,
            dest_path=final_blob_name
        )
        
        if success:
            logger.info(f"Successfully moved to final location: {final_blob_name}")
            # Return URL of final location
            final_blob_client = self.blob_service.get_blob_client(
                container=self.silver_container,
                blob=final_blob_name
            )
            return final_blob_client.url
        else:
            logger.warning(f"Failed to move to final location, file remains in temp: {temp_blob_name}")
            return temp_blob_client.url
    
    def _cleanup_chunks(self, job_id: str, chunk_urls: Dict):
        """
        Clean up chunk files from blob storage
        """
        logger.info(f"Cleaning up chunks for job {job_id}")
        
        # Delete all chunks for this job from the chunks folder in silver container
        container_client = self.blob_service.get_container_client(self.silver_container)
        
        # List and delete all blobs in the job's chunk folder
        chunk_prefix = f"{self.chunks_folder}/{job_id}/"
        blobs = container_client.list_blobs(name_starts_with=chunk_prefix)
        
        deleted_count = 0
        for blob in blobs:
            try:
                blob_client = container_client.get_blob_client(blob.name)
                blob_client.delete_blob()
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete chunk {blob.name}: {e}")
        
        logger.info(f"Deleted {deleted_count} chunk files for job {job_id}")
    
    def _save_state(self, job_id: str, state: Dict):
        """Save job state to blob storage"""
        state_blob = f"{job_id}_state.json"
        blob_client = self.blob_service.get_blob_client(
            container=self.state_container,
            blob=state_blob
        )
        
        # Pretty print for debugging
        state_json = json.dumps(state, indent=2, default=str)
        blob_client.upload_blob(state_json, overwrite=True)
    
    def _load_state(self, job_id: str) -> Dict:
        """Load job state from blob storage"""
        state_blob = f"{job_id}_state.json"
        blob_client = self.blob_service.get_blob_client(
            container=self.state_container,
            blob=state_blob
        )
        
        state_json = blob_client.download_blob().readall()
        return json.loads(state_json)
    
    def _queue_chunk(self, job_id: str, chunk_id: int):
        """Queue a chunk for processing"""
        from azure.storage.queue import QueueServiceClient
        from azure.identity import DefaultAzureCredential
        from config import Config
        import base64
        
        # Get queue client - use existing geospatial-tasks queue
        account_url = Config.get_storage_account_url('queue')
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        queue_client = queue_service.get_queue_client('geospatial-tasks')
        
        # Ensure queue exists
        try:
            queue_client.create_queue()
        except:
            pass  # Queue already exists
        
        message = {
            'job_id': job_id,
            'operation': 'process_chunk',
            'chunk_id': chunk_id,
            'task_type': 'chunk_processing'  # Add task type for routing
        }
        
        # Send message with Base64 encoding
        message_content = json.dumps(message)
        encoded_message = base64.b64encode(message_content.encode('utf-8')).decode('ascii')
        queue_client.send_message(encoded_message)
        
        logger.info(f"Queued chunk {chunk_id} for job {job_id} to geospatial-tasks")
    
    def _queue_assembly(self, job_id: str):
        """Queue the final assembly job"""
        from azure.storage.queue import QueueServiceClient
        from azure.identity import DefaultAzureCredential
        from config import Config
        import base64
        
        # Get queue client - use existing geospatial-tasks queue
        account_url = Config.get_storage_account_url('queue')
        queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        queue_client = queue_service.get_queue_client('geospatial-tasks')
        
        # Ensure queue exists
        try:
            queue_client.create_queue()
        except:
            pass  # Queue already exists
        
        message = {
            'job_id': job_id,
            'operation': 'assemble_chunks',  # Match the operation name in function_app
            'task_type': 'chunk_assembly'  # Add task type for routing
        }
        
        # Send message with Base64 encoding
        message_content = json.dumps(message)
        encoded_message = base64.b64encode(message_content.encode('utf-8')).decode('ascii')
        queue_client.send_message(encoded_message)
        
        logger.info(f"Queued assembly for job {job_id} to geospatial-tasks")


class ChunkedMosaicService:
    """
    High-level service for chunked mosaic operations
    Implements BaseProcessingService interface for Azure Functions
    """
    
    def __init__(self):
        self.processor = ChunkedRasterProcessor()
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["chunked_mosaic"]
    
    def process(self, **kwargs) -> Dict[str, Any]:
        """
        Process a chunked mosaic job (Azure Functions interface)
        
        Args:
            job_id: Unique job identifier
            dataset_id: Container name for input files
            resource_id: Comma-separated list of input files
            version_id: Output file name
            operation_type: Should be 'chunked_mosaic'
            
        Returns:
            Processing result
        """
        import json
        
        # Extract parameters from kwargs
        job_id = kwargs.get('job_id', '')
        dataset_id = kwargs.get('dataset_id', '')
        resource_id = kwargs.get('resource_id', '')
        version_id = kwargs.get('version_id', '')
        operation_type = kwargs.get('operation_type', '')
        
        # Parse input files
        if resource_id.startswith('['):
            input_files = json.loads(resource_id)
        else:
            input_files = [f.strip() for f in resource_id.split(',')]
        
        # Start chunked mosaic with proper container
        return self.start_chunked_mosaic(
            job_id=job_id,
            input_files=input_files,
            source_container=dataset_id,
            output_name=version_id if version_id else "mosaic_output",
            target_crs="EPSG:4326"
        )
    
    def start_chunked_mosaic(self, job_id: str, input_files: List[str], 
                            source_container: str, output_name: str, 
                            target_crs: str = "EPSG:4326") -> Dict:
        """
        Create a mosaic using chunked processing
        Can handle ANY size input
        """
        try:
            # Start the chunked processing
            job_state = self.processor.start_chunked_mosaic(
                job_id, input_files, source_container, output_name, target_crs
            )
            
            return {
                'success': True,
                'job_id': job_id,
                'status': 'processing',
                'total_chunks': job_state['grid']['total_chunks'],
                'message': f"Chunked mosaic started with {job_state['grid']['total_chunks']} chunks"
            }
            
        except Exception as e:
            logger.error(f"Error starting chunked mosaic: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_progress(self, job_id: str) -> Dict:
        """Get progress of a chunked mosaic job"""
        try:
            job_state = self.processor._load_state(job_id)
            
            return {
                'success': True,
                'job_id': job_id,
                'status': job_state['status'],
                'progress': job_state['progress'],
                'chunks_completed': len(job_state['chunks_completed']),
                'total_chunks': job_state['grid']['total_chunks'],
                'output_url': job_state.get('output_url')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f"Job not found: {str(e)}"
            }
    
    def process(self, **kwargs) -> Dict[str, Any]:
        """
        Process method required by base class.
        Routes to appropriate chunked processing method.
        
        Args:
            operation: Type of operation (mosaic, process_large, etc.)
            **kwargs: Additional parameters for the operation
            
        Returns:
            Processing result dictionary
        """
        operation = kwargs.get('operation', 'mosaic')
        
        if operation == 'mosaic':
            return self.process_mosaic_chunked(
                kwargs.get('input_files', []),
                kwargs.get('source_container', self.bronze_container),
                kwargs.get('output_name'),
                kwargs.get('target_crs', 'EPSG:4326')
            )
        else:
            raise ValueError(f"Unknown operation: {operation}")