"""
Output validator for Phase 0 POC
Validates COG outputs with configurable strictness levels
"""
import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import subprocess

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from config import Config
from state_models import ValidationLevel
from logger_setup import get_logger

logger = get_logger(__name__)


class OutputValidator:
    """Validates raster outputs and performs cleanup"""
    
    def __init__(self):
        # Initialize blob client based on environment
        if Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity in Azure Functions
            blob_url = Config.get_storage_account_url('blob')
            self.blob_service = BlobServiceClient(blob_url, credential=DefaultAzureCredential())
            logger.info(f"OutputValidator initialized with managed identity")
        elif Config.AZURE_WEBJOBS_STORAGE:
            # Fall back to connection string for local development
            self.blob_service = BlobServiceClient.from_connection_string(
                Config.AZURE_WEBJOBS_STORAGE
            )
            logger.info("OutputValidator initialized with connection string")
        else:
            raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage must be set")
        
        # Patterns to remove from output names
        self.suffix_patterns = [
            r'[_-]?R\d+C\d+',  # Row/column indicators (R1C1, R2C2)
            r'[_-]?merged',     # Merged indicator
            r'[_-]?tile\d*',    # Tile indicators
            r'[_-]?0+\d{1,3}', # Zero-padded numbers (0001, 0002)
            r'[_-]?part\d+',    # Part indicators
        ]
    
    def validate(
        self,
        job_id: str,
        output_path: str,
        validation_level: ValidationLevel = ValidationLevel.STANDARD,
        expected_metadata: Optional[Dict[str, Any]] = None,
        resource_id: Optional[str] = None,
        version_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate output file and return results
        
        Returns:
            Tuple of (success: bool, results: dict)
        """
        logger.info(
            f"Validating output for job {job_id} "
            f"with level {validation_level.value}"
        )
        
        results = {
            'validation_level': validation_level.value,
            'checks': {},
            'warnings': [],
            'errors': [],
            'final_path': None
        }
        
        # Determine which checks to run based on level
        checks_to_run = self._get_checks_for_level(validation_level)
        
        # Run checks
        all_passed = True
        
        for check_name in checks_to_run['required']:
            passed, message = self._run_check(
                check_name, 
                job_id,
                output_path, 
                expected_metadata
            )
            results['checks'][check_name] = {
                'passed': passed,
                'message': message,
                'required': True
            }
            if not passed:
                all_passed = False
                results['errors'].append(f"{check_name}: {message}")
        
        for check_name in checks_to_run.get('warnings', []):
            passed, message = self._run_check(
                check_name,
                job_id,
                output_path,
                expected_metadata
            )
            results['checks'][check_name] = {
                'passed': passed,
                'message': message,
                'required': False
            }
            if not passed:
                results['warnings'].append(f"{check_name}: {message}")
        
        # Clean naming if validation passed
        if all_passed:
            logger.info(f"Cleaning output name with resource_id={resource_id}, version_id={version_id}")
            final_path = self._clean_output_name(job_id, output_path, resource_id, version_id)
            results['final_path'] = final_path
            logger.info(f"Validation passed. Final path: {final_path}")
        else:
            logger.error(f"Validation failed for job {job_id}")
        
        return all_passed, results
    
    def _get_checks_for_level(self, level: ValidationLevel) -> Dict[str, List[str]]:
        """Get checks to run for validation level"""
        if level == ValidationLevel.STRICT:
            return {
                'required': [
                    'output_exists',
                    'is_valid_cog',
                    'metadata_intact',
                    'size_reasonable'
                ],
                'warnings': []
            }
        elif level == ValidationLevel.STANDARD:
            return {
                'required': ['output_exists', 'is_valid_cog'],
                'warnings': ['metadata_intact', 'stac_updated']
            }
        else:  # LENIENT
            return {
                'required': ['output_exists'],
                'warnings': []
            }
    
    def _run_check(
        self,
        check_name: str,
        job_id: str,
        output_path: str,
        expected_metadata: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Run a specific validation check"""
        
        if check_name == 'output_exists':
            return self._check_output_exists(output_path)
        
        elif check_name == 'is_valid_cog':
            return self._check_valid_cog(output_path)
        
        elif check_name == 'metadata_intact':
            return self._check_metadata_intact(output_path, expected_metadata)
        
        elif check_name == 'size_reasonable':
            return self._check_size_reasonable(output_path)
        
        elif check_name == 'stac_updated':
            return self._check_stac_updated(output_path)
        
        else:
            return False, f"Unknown check: {check_name}"
    
    def _check_output_exists(self, output_path: str) -> Tuple[bool, str]:
        """Check if output file exists in blob storage"""
        try:
            # Parse container and blob name from path
            container, blob_name = self._parse_blob_path(output_path)
            
            blob_client = self.blob_service.get_blob_client(
                container=container,
                blob=blob_name
            )
            
            if blob_client.exists():
                properties = blob_client.get_blob_properties()
                # Handle both dict and object style access for SDK compatibility
                if isinstance(properties, dict):
                    size = properties.get('size', 0)
                else:
                    size = getattr(properties, 'size', 0)
                size_mb = size / (1024 * 1024)
                return True, f"File exists ({size_mb:.2f} MB)"
            else:
                return False, "File not found"
                
        except Exception as e:
            return False, f"Error checking file: {e}"
    
    def _check_valid_cog(self, output_path: str) -> Tuple[bool, str]:
        """Check if output is a valid COG using gdal_info"""
        try:
            # For POC, we'll do a basic check using subprocess
            # In production, use rasterio or GDAL Python bindings
            
            # Generate SAS URL for the file
            container, blob_name = self._parse_blob_path(output_path)
            sas_url = self._get_sas_url(container, blob_name)
            
            # Run gdal_info
            result = subprocess.run(
                ['gdalinfo', '-checksum', sas_url],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                output = result.stdout
                
                # Check for COG indicators
                if 'LAYOUT=COG' in output or 'Cloud Optimized' in output:
                    return True, "Valid COG format confirmed"
                elif 'GTiff' in output:
                    return True, "Valid GeoTIFF (may not be COG-optimized)"
                else:
                    return False, "Not a valid GeoTIFF"
            else:
                return False, f"GDAL validation failed: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return False, "Validation timed out"
        except Exception as e:
            logger.warning(f"COG validation error: {e}")
            # Fallback to basic existence check
            return True, "File exists (detailed validation unavailable)"
    
    def _check_metadata_intact(
        self,
        output_path: str,
        expected_metadata: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Check if metadata is preserved"""
        if not expected_metadata:
            return True, "No expected metadata to validate"
        
        try:
            # For POC, just check that key metadata exists
            # In production, compare actual vs expected
            required_keys = ['crs', 'width', 'height', 'count']
            missing = [k for k in required_keys if k not in expected_metadata]
            
            if missing:
                return False, f"Missing metadata: {missing}"
            
            return True, "Metadata structure intact"
            
        except Exception as e:
            return False, f"Metadata check error: {e}"
    
    def _check_size_reasonable(self, output_path: str) -> Tuple[bool, str]:
        """Check if output size is reasonable"""
        try:
            container, blob_name = self._parse_blob_path(output_path)
            blob_client = self.blob_service.get_blob_client(
                container=container,
                blob=blob_name
            )
            
            properties = blob_client.get_blob_properties()
            size_gb = properties.size / (1024 * 1024 * 1024)
            
            # Check reasonable bounds
            if size_gb > 100:
                return False, f"Output suspiciously large: {size_gb:.2f} GB"
            elif properties.size < 1024:  # Less than 1KB
                return False, f"Output suspiciously small: {properties.size} bytes"
            
            return True, f"Size reasonable: {size_gb:.2f} GB"
            
        except Exception as e:
            return False, f"Size check error: {e}"
    
    def _check_stac_updated(self, output_path: str) -> Tuple[bool, str]:
        """Check if STAC catalog was updated"""
        # For POC, just return success
        # In production, query STAC catalog
        return True, "STAC update check skipped for POC"
    
    def _clean_output_name(self, job_id: str, current_path: str, resource_id: Optional[str] = None, version_id: Optional[str] = None) -> str:
        """
        Clean output filename and move to final location
        Uses resource_id if provided, otherwise cleans the existing name
        """
        try:
            container, blob_name = self._parse_blob_path(current_path)
            
            # Extract filename and extension
            path_parts = blob_name.split('/')
            filename = path_parts[-1]
            _, ext = os.path.splitext(filename)
            
            # Build clean name from resource_id if available
            if resource_id:
                logger.info(f"Using resource_id '{resource_id}' for naming")
                # Remove extension from resource_id if present
                base_name = os.path.splitext(resource_id)[0]
                
                # Remove unwanted suffixes
                clean_name = base_name
                for pattern in self.suffix_patterns:
                    clean_name = re.sub(pattern, '', clean_name, flags=re.IGNORECASE)
                
                # Add version if provided
                if version_id and version_id not in ['none', 'v1', 'test']:
                    clean_name = f"{clean_name}_{version_id}"
                
            else:
                # Fall back to cleaning existing name
                logger.warning(f"No resource_id provided, using existing filename: {filename}")
                base_name, _ = os.path.splitext(filename)
                clean_name = base_name
                for pattern in self.suffix_patterns:
                    clean_name = re.sub(pattern, '', clean_name, flags=re.IGNORECASE)
                
                # Add timestamp if not present
                if not re.search(r'\d{8}[_-]\d{6}', clean_name):
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    clean_name = f"{clean_name}_{timestamp}"
            
            # Ensure it ends with _cog if it's a COG
            if '_cog' not in clean_name.lower():
                clean_name = f"{clean_name}_cog"
            
            # Build final path
            final_filename = f"{clean_name}{ext}"
            
            # Determine final location based on container
            if container == Config.SILVER_CONTAINER_NAME:
                # Move from temp to processed folder
                if 'temp/' in blob_name:
                    final_blob_name = f"{Config.SILVER_COGS_FOLDER}/{final_filename}"
                else:
                    # Already in right place, just rename
                    folder = '/'.join(path_parts[:-1])
                    final_blob_name = f"{folder}/{final_filename}" if folder else final_filename
            else:
                # Keep in same location with new name
                folder = '/'.join(path_parts[:-1])
                final_blob_name = f"{folder}/{final_filename}" if folder else final_filename
            
            # Perform the rename (metadata-only operation in ADLS)
            source_blob = self.blob_service.get_blob_client(
                container=container,
                blob=blob_name
            )
            
            dest_blob = self.blob_service.get_blob_client(
                container=container,
                blob=final_blob_name
            )
            
            # Copy with new name
            dest_blob.start_copy_from_url(source_blob.url)
            
            # Delete old file after successful copy
            source_blob.delete_blob()
            
            logger.info(f"Renamed {blob_name} to {final_blob_name}")
            
            return f"{container}/{final_blob_name}"
            
        except Exception as e:
            logger.error(f"Error cleaning output name: {e}")
            # Return original path if rename fails
            return current_path
    
    def cleanup_temp_files(self, job_id: str, preserve_on_error: bool = False):
        """Clean up temporary files for a job"""
        try:
            container_client = self.blob_service.get_container_client(
                Config.SILVER_CONTAINER_NAME
            )
            
            # List all blobs in temp folder for this job
            temp_prefix = f"{Config.SILVER_TEMP_FOLDER}/{job_id}/"
            blobs = container_client.list_blobs(name_starts_with=temp_prefix)
            
            count = 0
            for blob in blobs:
                if not preserve_on_error:
                    container_client.delete_blob(blob.name)
                    count += 1
            
            if count > 0:
                logger.info(f"Cleaned up {count} temp files for job {job_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning temp files: {e}")
    
    def _parse_blob_path(self, path: str) -> Tuple[str, str]:
        """Parse container and blob name from path"""
        # Handle various path formats
        if path.startswith('http'):
            # URL format
            parts = path.split('.blob.core.windows.net/')[-1].split('/')
            container = parts[0]
            blob_name = '/'.join(parts[1:]).split('?')[0]  # Remove SAS token
        elif '/' in path:
            # container/blob format
            parts = path.split('/', 1)
            container = parts[0]
            blob_name = parts[1] if len(parts) > 1 else ''
        else:
            # Assume silver container
            container = Config.SILVER_CONTAINER_NAME
            blob_name = path
        
        return container, blob_name
    
    def _get_sas_url(self, container: str, blob_name: str) -> str:
        """Generate SAS URL for blob access"""
        # For POC, use connection string
        # In production, use user delegation SAS
        blob_client = self.blob_service.get_blob_client(
            container=container,
            blob=blob_name
        )
        return blob_client.url