"""
Raster Mosaic Service - Merges multiple TIFF files into a single mosaic
Handles tiled scenes and multi-part acquisitions
"""
import os
import tempfile
from typing import List, Dict, Optional, Tuple
import rasterio
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
from logger_setup import logger


class RasterMosaicService:
    """
    Service for merging multiple raster files into a single mosaic
    Supports automatic alignment, reprojection, and nodata handling
    """
    
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
    
    def create_mosaic(self, 
                      input_files: List[str], 
                      output_path: str,
                      target_crs: Optional[str] = None,
                      resolution: Optional[float] = None,
                      resampling_method: str = 'bilinear',
                      nodata_value: Optional[float] = None) -> Dict:
        """
        Create a mosaic from multiple input raster files
        
        Args:
            input_files: List of paths/URLs to input raster files
            output_path: Path for output mosaic file
            target_crs: Target CRS (EPSG code or proj string). If None, uses first file's CRS
            resolution: Target resolution in units of target_crs. If None, uses finest resolution
            resampling_method: Resampling method (nearest, bilinear, cubic, etc.)
            nodata_value: NoData value for output. If None, uses first file's nodata
            
        Returns:
            Dict with mosaic metadata and statistics
        """
        try:
            logger.info(f"Starting mosaic creation from {len(input_files)} input files")
            
            if len(input_files) < 2:
                raise ValueError("At least 2 input files required for mosaic")
            
            # Open all input datasets
            datasets = []
            for file_path in input_files:
                logger.info(f"Opening input: {file_path}")
                if file_path.startswith('http'):
                    # Handle remote files via GDAL virtual file system
                    ds = rasterio.open(file_path)
                else:
                    ds = rasterio.open(file_path)
                datasets.append(ds)
            
            # Determine target CRS and resolution
            if target_crs:
                if isinstance(target_crs, str) and target_crs.startswith('EPSG:'):
                    target_crs = CRS.from_epsg(int(target_crs.split(':')[1]))
                else:
                    target_crs = CRS.from_string(target_crs)
            else:
                target_crs = datasets[0].crs
                logger.info(f"Using CRS from first file: {target_crs}")
            
            # Check if all files have same CRS
            need_reprojection = any(ds.crs != target_crs for ds in datasets)
            if need_reprojection:
                logger.info("Input files have different CRS - reprojection required")
            
            # Determine output resolution
            if not resolution:
                # Use the finest (smallest) resolution from all inputs
                resolutions = []
                for ds in datasets:
                    if ds.crs == target_crs:
                        resolutions.append(ds.res[0])  # Assuming square pixels
                    else:
                        # Calculate resolution in target CRS
                        transform, width, height = calculate_default_transform(
                            ds.crs, target_crs, ds.width, ds.height, *ds.bounds
                        )
                        res = transform[0]  # Cell width
                        resolutions.append(abs(res))
                
                resolution = min(resolutions)
                logger.info(f"Using finest resolution: {resolution}")
            
            # Get resampling method
            resampling_map = {
                'nearest': Resampling.nearest,
                'bilinear': Resampling.bilinear,
                'cubic': Resampling.cubic,
                'cubic_spline': Resampling.cubic_spline,
                'lanczos': Resampling.lanczos,
                'average': Resampling.average,
                'mode': Resampling.mode
            }
            resampling = resampling_map.get(resampling_method, Resampling.bilinear)
            
            # Determine nodata value
            if nodata_value is None:
                nodata_value = datasets[0].nodata
                if nodata_value is None:
                    nodata_value = 0  # Default to 0 if no nodata defined
            
            # If reprojection is needed, reproject datasets to temporary files first
            if need_reprojection:
                logger.info(f"Reprojecting datasets to {target_crs}")
                reprojected_datasets = []
                temp_files = []
                
                for ds in datasets:
                    if ds.crs != target_crs:
                        # Calculate transform for this dataset
                        transform, width, height = calculate_default_transform(
                            ds.crs, target_crs, ds.width, ds.height, *ds.bounds,
                            resolution=resolution
                        )
                        
                        # Create temporary file for reprojected data
                        import tempfile
                        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
                        temp_files.append(tmp.name)
                        tmp.close()
                        
                        # Reproject to temporary file
                        profile = ds.profile.copy()
                        profile.update({
                            'crs': target_crs,
                            'transform': transform,
                            'width': width,
                            'height': height
                        })
                        
                        with rasterio.open(tmp.name, 'w', **profile) as dst:
                            for i in range(1, ds.count + 1):
                                reproject(
                                    source=rasterio.band(ds, i),
                                    destination=rasterio.band(dst, i),
                                    src_transform=ds.transform,
                                    src_crs=ds.crs,
                                    dst_transform=transform,
                                    dst_crs=target_crs,
                                    resampling=resampling
                                )
                        
                        # Open reprojected file
                        reprojected_datasets.append(rasterio.open(tmp.name))
                    else:
                        reprojected_datasets.append(ds)
                
                # Use reprojected datasets for merge
                datasets_to_merge = reprojected_datasets
            else:
                datasets_to_merge = datasets
            
            # Perform the merge
            logger.info("Merging rasters...")
            # Convert resolution to tuple if it's a single value
            if resolution:
                res_param = (resolution, resolution)  # Use same resolution for x and y
            else:
                res_param = None
            
            mosaic, out_transform = merge(
                datasets_to_merge,
                res=res_param,
                nodata=nodata_value,
                resampling=resampling,
                method='max'  # Use max value for overlapping areas
            )
            
            # Calculate output bounds
            bounds = rasterio.transform.array_bounds(
                mosaic.shape[1], mosaic.shape[2], out_transform
            )
            
            # Write output mosaic
            logger.info(f"Writing mosaic to: {output_path}")
            profile = {
                'driver': 'GTiff',
                'height': mosaic.shape[1],
                'width': mosaic.shape[2],
                'count': mosaic.shape[0],
                'dtype': mosaic.dtype,
                'crs': target_crs,
                'transform': out_transform,
                'nodata': nodata_value,
                'compress': 'lzw',
                'tiled': True,
                'blockxsize': 512,
                'blockysize': 512
            }
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(mosaic)
                
                # Add overviews for better performance
                factors = [2, 4, 8, 16, 32]
                dst.build_overviews(factors, Resampling.average)
                dst.update_tags(ns='rio_overview', resampling='average')
            
            # Close input datasets
            for ds in datasets:
                ds.close()
            
            # Clean up reprojected datasets and temp files if any
            if need_reprojection and 'reprojected_datasets' in locals():
                for ds in reprojected_datasets:
                    if ds not in datasets:  # Only close reprojected ones
                        ds.close()
                if 'temp_files' in locals():
                    import os
                    for tmp_file in temp_files:
                        try:
                            os.remove(tmp_file)
                        except:
                            pass
            
            # Gather statistics
            result = {
                'success': True,
                'output_path': output_path,
                'input_count': len(input_files),
                'output_crs': str(target_crs),
                'output_resolution': resolution,
                'output_bounds': bounds,
                'output_shape': {
                    'height': mosaic.shape[1],
                    'width': mosaic.shape[2],
                    'bands': mosaic.shape[0]
                },
                'nodata_value': nodata_value,
                'reprojection_applied': need_reprojection,
                'resampling_method': resampling_method
            }
            
            logger.info(f"Mosaic created successfully: {mosaic.shape[2]}x{mosaic.shape[1]} pixels")
            return result
            
        except Exception as e:
            logger.error(f"Error creating mosaic: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'input_files': input_files
            }
    
    def validate_inputs(self, input_files: List[str]) -> Dict:
        """
        Validate that input files are compatible for mosaicking
        
        Args:
            input_files: List of input file paths/URLs
            
        Returns:
            Dict with validation results and compatibility information
        """
        try:
            if len(input_files) < 2:
                return {
                    'valid': False,
                    'error': 'At least 2 input files required'
                }
            
            # Open and check each file
            file_info = []
            crs_list = []
            dtype_list = []
            band_counts = []
            
            for file_path in input_files:
                try:
                    with rasterio.open(file_path) as ds:
                        info = {
                            'path': file_path,
                            'crs': str(ds.crs) if ds.crs else 'None',
                            'bounds': ds.bounds,
                            'resolution': ds.res,
                            'shape': (ds.height, ds.width),
                            'bands': ds.count,
                            'dtype': str(ds.dtypes[0]),
                            'nodata': ds.nodata
                        }
                        file_info.append(info)
                        crs_list.append(ds.crs)
                        dtype_list.append(ds.dtypes[0])
                        band_counts.append(ds.count)
                except Exception as e:
                    return {
                        'valid': False,
                        'error': f"Cannot open file {file_path}: {str(e)}"
                    }
            
            # Check compatibility
            warnings = []
            
            # Check CRS consistency
            unique_crs = set(str(crs) for crs in crs_list if crs)
            if len(unique_crs) > 1:
                warnings.append(f"Multiple CRS detected: {list(unique_crs)}. Reprojection will be applied.")
            
            # Check band count consistency
            unique_bands = set(band_counts)
            if len(unique_bands) > 1:
                warnings.append(f"Inconsistent band counts: {list(unique_bands)}. May cause issues.")
            
            # Check data type consistency
            unique_dtypes = set(str(dt) for dt in dtype_list)
            if len(unique_dtypes) > 1:
                warnings.append(f"Multiple data types: {list(unique_dtypes)}. Will use first file's dtype.")
            
            # Calculate combined bounds (in first file's CRS)
            if crs_list[0]:
                min_x = min(info['bounds'][0] for info in file_info)
                min_y = min(info['bounds'][1] for info in file_info)
                max_x = max(info['bounds'][2] for info in file_info)
                max_y = max(info['bounds'][3] for info in file_info)
                combined_bounds = (min_x, min_y, max_x, max_y)
            else:
                combined_bounds = None
            
            return {
                'valid': True,
                'file_count': len(input_files),
                'files': file_info,
                'warnings': warnings,
                'combined_bounds': combined_bounds,
                'recommended_crs': str(crs_list[0]) if crs_list[0] else None,
                'band_count': band_counts[0] if unique_bands else None
            }
            
        except Exception as e:
            return {
                'valid': False,
                'error': f"Validation error: {str(e)}"
            }
    
    def detect_tile_pattern(self, file_list: List[str]) -> Dict:
        """
        Detect if files follow a tile pattern and estimate grid configuration
        
        Args:
            file_list: List of file paths
            
        Returns:
            Dict with tile pattern information
        """
        import re
        
        # Extract just filenames
        filenames = [os.path.basename(f) for f in file_list]
        
        # Common tile patterns
        patterns = {
            'numbered': re.compile(r'(.+?)[\-_](\d+)\.(tif|tiff)$', re.IGNORECASE),
            'row_col': re.compile(r'(.+?)[\-_]r(\d+)c(\d+)\.(tif|tiff)$', re.IGNORECASE),
            'grid': re.compile(r'(.+?)[\-_]([A-Z])(\d+)\.(tif|tiff)$', re.IGNORECASE),
            'xy': re.compile(r'(.+?)[\-_]x(\d+)y(\d+)\.(tif|tiff)$', re.IGNORECASE)
        }
        
        for pattern_name, pattern in patterns.items():
            matches = []
            base_names = set()
            
            for fname in filenames:
                match = pattern.match(fname)
                if match:
                    matches.append(match)
                    base_names.add(match.group(1))
            
            if len(matches) == len(filenames) and len(base_names) == 1:
                # All files match the pattern with same base name
                base_name = list(base_names)[0]
                
                if pattern_name == 'numbered':
                    # Simple numbered sequence
                    numbers = sorted([int(m.group(2)) for m in matches])
                    return {
                        'detected': True,
                        'pattern_type': 'numbered',
                        'base_name': base_name,
                        'tile_count': len(numbers),
                        'tile_ids': numbers,
                        'estimated_grid': self._estimate_grid(len(numbers))
                    }
                
                elif pattern_name == 'row_col':
                    # Row/column grid
                    coords = [(int(m.group(2)), int(m.group(3))) for m in matches]
                    rows = max(r for r, c in coords)
                    cols = max(c for r, c in coords)
                    return {
                        'detected': True,
                        'pattern_type': 'row_column',
                        'base_name': base_name,
                        'tile_count': len(coords),
                        'grid_size': f"{rows}x{cols}",
                        'coordinates': coords
                    }
        
        return {
            'detected': False,
            'message': 'No consistent tile pattern detected'
        }
    
    def _estimate_grid(self, count: int) -> str:
        """Estimate grid dimensions from tile count"""
        if count == 4:
            return "2x2"
        elif count == 9:
            return "3x3"
        elif count == 16:
            return "4x4"
        elif count == 25:
            return "5x5"
        else:
            # Try to factor
            import math
            sqrt = int(math.sqrt(count))
            if sqrt * sqrt == count:
                return f"{sqrt}x{sqrt}"
            return f"{count} tiles"