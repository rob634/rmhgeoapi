"""
Metadata Inference Service - Pattern recognition and metadata extraction from filenames and paths
Enriches container listings with inferred metadata without downloading files
"""
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict
from logger_setup import logger


class MetadataInferenceService:
    """
    Service for inferring metadata from file paths and names
    Recognizes vendor patterns, file relationships, and data characteristics
    """
    
    def __init__(self):
        self.patterns = self._initialize_patterns()
        self.relationships = defaultdict(list)
        self.scenes = defaultdict(list)
    
    def _initialize_patterns(self) -> Dict:
        """Initialize regex patterns for various vendors and file types"""
        return {
            'maxar': {
                'pattern': re.compile(
                    r'(?P<sensor>WV0[1-4]|GE01|QB02)_'
                    r'(?P<date>\d{8})(?P<time>\d{6})?_?'
                    r'(?P<product>[A-Z0-9]+)?_?'
                    r'(?P<catalog_id>[A-Z0-9]{16})?'
                ),
                'metadata': {
                    'vendor': 'Maxar',
                    'type': 'satellite_imagery'
                },
                'sidecar_extensions': ['.xml', '.imd', '.rpb', '.til', '.aux.xml']
            },
            'planet': {
                'pattern': re.compile(
                    r'(?P<date>\d{8})_(?P<time>\d{6})_'
                    r'(?P<satellite_id>\d{2}_[a-z0-9]+)_'
                    r'(?P<product_type>[a-z]+)'
                ),
                'metadata': {
                    'vendor': 'Planet',
                    'type': 'satellite_imagery'
                },
                'sidecar_extensions': ['.json', '_metadata.json']
            },
            'sentinel': {
                'pattern': re.compile(
                    r'S(?P<mission>1|2)[AB]_'
                    r'(?P<mode>[A-Z]{2})_'
                    r'(?P<product>[A-Z0-9]+)_'
                    r'(?P<date>\d{8})T(?P<time>\d{6})'
                ),
                'metadata': {
                    'vendor': 'ESA/Copernicus',
                    'type': 'satellite_imagery'
                }
            },
            'landsat': {
                'pattern': re.compile(
                    r'L(?P<sensor>[COTE])(?P<satellite>\d{2})_'
                    r'(?P<level>[A-Z0-9]+)_'
                    r'(?P<path>\d{3})(?P<row>\d{3})_'
                    r'(?P<date>\d{8})'
                ),
                'metadata': {
                    'vendor': 'USGS/NASA',
                    'type': 'satellite_imagery'
                }
            },
            'cog_indicator': {
                'pattern': re.compile(r'.*[_\-]cog\.tiff?$', re.IGNORECASE),
                'metadata': {
                    'likely_cog': True,
                    'processing_level': 'optimized'
                }
            },
            'tile_pattern': {
                'patterns': [
                    # Pattern 1: Simple numbered tiles (scene_1.tif, scene_2.tif)
                    re.compile(
                        r'(?P<scene_name>.+?)[_\-]'
                        r'(?P<tile_num>\d+)'
                        r'(?P<suffix>[_\-]cog)?'
                        r'\.(?P<ext>tiff?|jp2|png)$',
                        re.IGNORECASE
                    ),
                    # Pattern 2: Row/Column tiles (scene_row1col1.tif, scene_r1c1.tif)
                    re.compile(
                        r'(?P<scene_name>.+?)[_\-]'
                        r'(?P<row_col>row\d+col\d+|r\d+c\d+)'
                        r'(?P<suffix>[_\-]cog)?'
                        r'\.(?P<ext>tiff?|jp2|png)$',
                        re.IGNORECASE
                    ),
                    # Pattern 3: Grid reference (scene_A1.tif, scene_B2.tif)
                    re.compile(
                        r'(?P<scene_name>.+?)[_\-]'
                        r'(?P<grid>[A-Z]\d+)'
                        r'(?P<suffix>[_\-]cog)?'
                        r'\.(?P<ext>tiff?|jp2|png)$',
                        re.IGNORECASE
                    ),
                    # Pattern 4: Quadrant style (scene_NW.tif, scene_SE.tif)
                    re.compile(
                        r'(?P<scene_name>.+?)[_\-]'
                        r'(?P<quadrant>NW|NE|SW|SE|N|S|E|W)'
                        r'(?P<suffix>[_\-]cog)?'
                        r'\.(?P<ext>tiff?|jp2|png)$',
                        re.IGNORECASE
                    ),
                    # Pattern 5: Part notation (scene_part1.tif, scene_p1.tif)
                    re.compile(
                        r'(?P<scene_name>.+?)[_\-]'
                        r'(?P<part>part\d+|p\d+)'
                        r'(?P<suffix>[_\-]cog)?'
                        r'\.(?P<ext>tiff?|jp2|png)$',
                        re.IGNORECASE
                    )
                ],
                'metadata': {
                    'type': 'tiled_scene',
                    'requires_mosaic': True
                }
            },
            'maxar_tile_pattern': {
                # Maxar specific: Same catalog ID but different part numbers
                'pattern': re.compile(
                    r'(?P<sensor>WV0[1-4]|GE01)_'
                    r'(?P<date>\d{8}).*?_'
                    r'(?P<catalog_id>[A-Z0-9]{16})'
                    r'.*?(?P<part>P\d{3}|part\d+)?',
                    re.IGNORECASE
                ),
                'metadata': {
                    'vendor': 'Maxar',
                    'type': 'multi_part_acquisition'
                }
            },
            'processing_levels': {
                'pattern': re.compile(
                    r'[_\-](?P<level>raw|l1[abc]?|l2[a]?|ortho|pan|ms|pansharp|toa|sr|nrg|ndvi)'
                    r'[_\-\.]',
                    re.IGNORECASE
                ),
                'metadata': {
                    'has_processing_indicator': True
                }
            },
            'date_patterns': {
                'pattern': re.compile(
                    r'(?P<year>20[12]\d)'
                    r'[_\-]?(?P<month>0[1-9]|1[0-2])'
                    r'[_\-]?(?P<day>[0-2]\d|3[01])'
                ),
                'metadata': {
                    'has_date': True
                }
            }
        }
    
    def infer_file_metadata(self, file_path: str, file_info: Dict) -> Dict:
        """
        Infer metadata from a single file path and info
        
        Args:
            file_path: Full path to the file
            file_info: Dict with size, last_modified, etc.
            
        Returns:
            Dict with original info plus inferred metadata
        """
        enriched = {**file_info}
        inferred = {}
        
        # Extract filename and directory parts
        parts = file_path.split('/')
        filename = parts[-1] if parts else file_path
        directory = '/'.join(parts[:-1]) if len(parts) > 1 else ''
        
        # Check vendor patterns
        vendor_matched = False
        for vendor_name, vendor_info in self.patterns.items():
            if 'pattern' not in vendor_info:
                continue
                
            match = vendor_info['pattern'].search(file_path)
            if match:
                vendor_matched = True
                inferred['vendor'] = vendor_info.get('metadata', {}).get('vendor', vendor_name)
                inferred.update(vendor_info.get('metadata', {}))
                
                # Extract named groups
                for key, value in match.groupdict().items():
                    if value:
                        inferred[f'extracted_{key}'] = value
                
                # Parse dates if found
                if 'date' in match.groupdict() and match.group('date'):
                    try:
                        date_str = match.group('date')
                        date_obj = datetime.strptime(date_str, '%Y%m%d')
                        inferred['acquisition_date'] = date_obj.isoformat()
                    except:
                        pass
                
                # Note sidecar expectations
                if 'sidecar_extensions' in vendor_info:
                    base_name = filename.rsplit('.', 1)[0]
                    expected_sidecars = [
                        base_name + ext for ext in vendor_info['sidecar_extensions']
                    ]
                    inferred['expected_sidecars'] = expected_sidecars
                
                # Special handling for Maxar nested paths
                if vendor_name == 'maxar' and 'maxar_delivery' in directory:
                    path_parts = directory.split('/')
                    if len(path_parts) >= 2:
                        inferred['order_id'] = path_parts[1] if len(path_parts) > 1 else None
                        if len(path_parts) > 2:
                            inferred['acquisition_id'] = path_parts[2]
        
        # Check for COG indicators
        if re.search(r'[_\-]cog\.tiff?$', filename, re.IGNORECASE):
            inferred['likely_cog'] = True
            inferred['skip_cog_conversion'] = True
        
        # Check for tile patterns (multi-part scenes)
        tile_patterns = self.patterns['tile_pattern']['patterns']
        for pattern in tile_patterns:
            tile_match = pattern.search(filename)
            if tile_match:
                scene_name = tile_match.group('scene_name')
                # Get tile identifier from various possible groups
                tile_id = (tile_match.groupdict().get('tile_num') or 
                          tile_match.groupdict().get('row_col') or
                          tile_match.groupdict().get('grid') or
                          tile_match.groupdict().get('quadrant') or
                          tile_match.groupdict().get('part', 'unknown'))
                
                inferred['scene_name'] = scene_name
                inferred['tile_identifier'] = tile_id
                inferred['part_of_tiled_scene'] = True
                
                # Track this for relationship mapping
                self.scenes[scene_name].append(file_path)
                break
        
        # Check for Maxar multi-part acquisitions (same catalog ID)
        maxar_match = self.patterns['maxar_tile_pattern']['pattern'].search(file_path)
        if maxar_match and maxar_match.group('catalog_id'):
            catalog_id = maxar_match.group('catalog_id')
            inferred['maxar_catalog_id'] = catalog_id
            inferred['part_of_acquisition'] = catalog_id
            # Group by catalog ID for Maxar scenes
            self.scenes[f"maxar_{catalog_id}"].append(file_path)
        
        # Check processing level indicators
        proc_match = self.patterns['processing_levels']['pattern'].search(filename)
        if proc_match:
            level = proc_match.group('level').lower()
            inferred['processing_level'] = level
            
            # Map to standard levels
            level_map = {
                'raw': 'L0',
                'l1a': 'L1A', 'l1b': 'L1B', 'l1c': 'L1C',
                'l2a': 'L2A',
                'ortho': 'orthorectified',
                'pan': 'panchromatic',
                'ms': 'multispectral', 
                'pansharp': 'pansharpened',
                'toa': 'top_of_atmosphere',
                'sr': 'surface_reflectance',
                'nrg': 'near_infrared',
                'ndvi': 'vegetation_index'
            }
            if level in level_map:
                inferred['standard_processing_level'] = level_map[level]
        
        # Infer file category
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext in ['tif', 'tiff', 'geotiff', 'cog', 'jp2', 'ntf']:
            inferred['data_category'] = 'raster'
            inferred['can_process_to_cog'] = not inferred.get('likely_cog', False)
        elif ext in ['geojson', 'json', 'gpkg', 'shp', 'kml', 'kmz', 'gml']:
            inferred['data_category'] = 'vector'
        elif ext in ['xml', 'imd', 'rpb', 'til', 'txt', 'pdf']:
            inferred['data_category'] = 'metadata'
        elif ext in ['png', 'jpg', 'jpeg']:
            inferred['data_category'] = 'preview'
        
        # Estimate if this is a sidecar file
        base_without_ext = filename.rsplit('.', 1)[0]
        if any(indicator in filename.lower() for indicator in ['metadata', 'aux', 'ovr']):
            inferred['likely_sidecar'] = True
            inferred['sidecar_for'] = base_without_ext.replace('_metadata', '').replace('.aux', '')
        
        # Add directory-based inference
        if directory:
            dir_lower = directory.lower()
            if 'bronze' in dir_lower:
                inferred['tier'] = 'bronze'
            elif 'silver' in dir_lower:
                inferred['tier'] = 'silver'
            elif 'gold' in dir_lower:
                inferred['tier'] = 'gold'
            
            # Project inference from path
            if 'maxar_delivery' in dir_lower:
                inferred['project'] = 'maxar_acquisition'
            elif any(proj in dir_lower for proj in ['namangan', 'yamatwa', 'antigua']):
                for proj in ['namangan', 'yamatwa', 'antigua']:
                    if proj in dir_lower:
                        inferred['project'] = proj
                        break
        
        # Size-based recommendations
        size_mb = file_info.get('size', 0) / (1024 * 1024)
        if size_mb > 1000:  # > 1GB
            inferred['large_file'] = True
            inferred['recommended_processing'] = 'smart_mode'
        elif size_mb > 5000:  # > 5GB
            inferred['very_large_file'] = True
            inferred['recommended_processing'] = 'header_only'
        
        # Add inference results
        if inferred:
            enriched['inferred_metadata'] = inferred
            enriched['inference_confidence'] = 'high' if vendor_matched else 'medium'
        
        return enriched
    
    def analyze_relationships(self, files: List[Dict]) -> Dict:
        """
        Analyze relationships between files in the container
        
        Args:
            files: List of file dictionaries
            
        Returns:
            Dict with relationship analysis
        """
        relationships = {
            'sidecar_pairs': [],
            'tiled_scenes': {},
            'file_groups': {},
            'orphan_sidecars': [],
            'complete_datasets': [],
            'potential_scenes': []  # Files that might be part of same scene
        }
        
        # Build lookup maps
        files_by_name = {f['name']: f for f in files}
        base_names = defaultdict(list)
        
        for file_info in files:
            name = file_info['name']
            # Get base name without extension
            if '.' in name:
                base = name.rsplit('.', 1)[0]
                # Also remove common suffixes
                for suffix in ['_metadata', '.aux', '_cog']:
                    base = base.replace(suffix, '')
                base_names[base].append(name)
        
        # Find sidecar relationships
        for base, related_files in base_names.items():
            if len(related_files) > 1:
                # Check if this is a data + metadata pair
                has_data = any(f.endswith(('.tif', '.tiff', '.jp2', '.ntf')) 
                             for f in related_files)
                has_metadata = any(f.endswith(('.xml', '.json', '.imd', '.rpb')) 
                                 for f in related_files)
                
                if has_data and has_metadata:
                    relationships['sidecar_pairs'].append({
                        'base_name': base,
                        'files': related_files,
                        'complete': True
                    })
        
        # Find tiled scenes
        for scene_name, scene_files in self.scenes.items():
            if len(scene_files) > 1:
                relationships['tiled_scenes'][scene_name] = {
                    'tiles': scene_files,
                    'tile_count': len(scene_files),
                    'estimated_grid': self._estimate_grid_size(len(scene_files)),
                    'scene_type': 'maxar_acquisition' if scene_name.startswith('maxar_') else 'tiled_raster'
                }
        
        # Find potential scenes based on similar characteristics
        self._detect_potential_scenes(files, relationships)
        
        # Find orphan sidecar files
        metadata_extensions = ['.xml', '.json', '.imd', '.rpb', '.til', '.aux.xml']
        for file_info in files:
            name = file_info['name']
            if any(name.endswith(ext) for ext in metadata_extensions):
                base = name.rsplit('.', 1)[0]
                # Check if corresponding data file exists
                potential_data_files = [
                    base + ext for ext in ['.tif', '.tiff', '.jp2', '.ntf']
                ]
                if not any(pdf in files_by_name for pdf in potential_data_files):
                    relationships['orphan_sidecars'].append(name)
        
        # Identify complete datasets (data + all expected metadata)
        for pair in relationships['sidecar_pairs']:
            files_in_pair = pair['files']
            if any('.tif' in f or '.tiff' in f for f in files_in_pair):
                # Check for Maxar complete set
                if any('.imd' in f for f in files_in_pair) and \
                   any('.rpb' in f for f in files_in_pair):
                    relationships['complete_datasets'].append({
                        'type': 'maxar_complete',
                        'base': pair['base_name'],
                        'files': files_in_pair
                    })
        
        return relationships
    
    def _estimate_grid_size(self, tile_count: int) -> str:
        """Estimate grid dimensions from tile count"""
        if tile_count == 4:
            return "2x2"
        elif tile_count == 9:
            return "3x3"
        elif tile_count == 16:
            return "4x4"
        elif tile_count == 2:
            return "1x2"
        else:
            return f"{tile_count} tiles"
    
    def _detect_potential_scenes(self, files: List[Dict], relationships: Dict):
        """
        Detect files that might be part of the same scene based on:
        - Similar names with different numbers
        - Same directory
        - Similar file sizes
        - Same acquisition date
        """
        # Group files by directory
        files_by_dir = defaultdict(list)
        for f in files:
            name = f['name']
            if '/' in name:
                dir_path = '/'.join(name.split('/')[:-1])
                files_by_dir[dir_path].append(f)
        
        # Analyze each directory for potential scenes
        for dir_path, dir_files in files_by_dir.items():
            # Only look at directories with multiple TIF files
            tif_files = [f for f in dir_files if f['name'].lower().endswith(('.tif', '.tiff'))]
            if len(tif_files) < 2:
                continue
            
            # Group by similar characteristics
            groups = defaultdict(list)
            
            for f in tif_files:
                # Extract base name without numbers and common suffixes
                name = f['name'].split('/')[-1]
                base = re.sub(r'[\d_\-]+\.(tiff?|jp2)$', '', name, flags=re.IGNORECASE)
                base = re.sub(r'(_part\d+|_p\d+|_tile\d+|_\d+)$', '', base, flags=re.IGNORECASE)
                
                # Check if file has inferred metadata
                meta = f.get('inferred_metadata', {})
                
                # Create grouping key based on common characteristics
                group_key = (
                    base,
                    meta.get('acquisition_date', 'unknown'),
                    meta.get('vendor', 'unknown'),
                    meta.get('processing_level', 'unknown')
                )
                
                groups[group_key].append(f)
            
            # Add groups with multiple files as potential scenes
            for group_key, group_files in groups.items():
                if len(group_files) > 1:
                    # Check if files have similar sizes (within 20% of mean)
                    sizes = [f.get('size', 0) for f in group_files]
                    if sizes:
                        mean_size = sum(sizes) / len(sizes)
                        size_variance = max(abs(s - mean_size) / mean_size for s in sizes if mean_size > 0)
                        
                        if size_variance < 0.2:  # Within 20% of mean
                            scene_info = {
                                'directory': dir_path,
                                'base_name': group_key[0],
                                'file_count': len(group_files),
                                'files': [f['name'] for f in group_files],
                                'acquisition_date': group_key[1],
                                'vendor': group_key[2],
                                'processing_level': group_key[3],
                                'confidence': 'high' if size_variance < 0.1 else 'medium',
                                'size_similarity': f"{(1 - size_variance) * 100:.1f}%"
                            }
                            
                            # Check if this isn't already identified as a tiled scene
                            already_identified = False
                            for scene_name in relationships['tiled_scenes']:
                                scene_tiles = relationships['tiled_scenes'][scene_name]['tiles']
                                if any(f['name'] in scene_tiles for f in group_files):
                                    already_identified = True
                                    break
                            
                            if not already_identified:
                                relationships['potential_scenes'].append(scene_info)
    
    def enrich_inventory(self, inventory: Dict) -> Dict:
        """
        Enrich a container inventory with inferred metadata
        
        Args:
            inventory: Container inventory dict with files list
            
        Returns:
            Enriched inventory with inference results
        """
        files = inventory.get('files', [])
        
        # Reset state for new analysis
        self.relationships.clear()
        self.scenes.clear()
        
        # Enrich each file
        enriched_files = []
        inference_stats = {
            'total_processed': 0,
            'vendor_identified': 0,
            'cog_detected': 0,
            'tiles_detected': 0,
            'sidecars_detected': 0
        }
        
        for file_info in files:
            enriched = self.infer_file_metadata(file_info['name'], file_info)
            enriched_files.append(enriched)
            
            # Update stats
            inference_stats['total_processed'] += 1
            if 'inferred_metadata' in enriched:
                meta = enriched['inferred_metadata']
                if 'vendor' in meta:
                    inference_stats['vendor_identified'] += 1
                if meta.get('likely_cog'):
                    inference_stats['cog_detected'] += 1
                if meta.get('part_of_tiled_scene'):
                    inference_stats['tiles_detected'] += 1
                if meta.get('likely_sidecar'):
                    inference_stats['sidecars_detected'] += 1
        
        # Analyze relationships
        relationships = self.analyze_relationships(enriched_files)
        
        # Create enriched inventory
        enriched_inventory = {
            **inventory,
            'files': enriched_files,
            'inference_analysis': {
                'statistics': inference_stats,
                'relationships': relationships,
                'vendor_summary': self._summarize_vendors(enriched_files),
                'processing_recommendations': self._generate_recommendations(enriched_files)
            }
        }
        
        return enriched_inventory
    
    def _summarize_vendors(self, files: List[Dict]) -> Dict:
        """Summarize files by vendor"""
        vendor_summary = defaultdict(lambda: {'count': 0, 'size_bytes': 0})
        
        for file_info in files:
            if 'inferred_metadata' in file_info:
                vendor = file_info['inferred_metadata'].get('vendor', 'unknown')
                vendor_summary[vendor]['count'] += 1
                vendor_summary[vendor]['size_bytes'] += file_info.get('size', 0)
        
        return dict(vendor_summary)
    
    def _generate_recommendations(self, files: List[Dict]) -> List[Dict]:
        """Generate processing recommendations based on analysis"""
        recommendations = []
        
        # Count COGs that don't need conversion
        cog_count = sum(1 for f in files 
                       if f.get('inferred_metadata', {}).get('likely_cog'))
        if cog_count > 0:
            recommendations.append({
                'type': 'optimization',
                'message': f"Found {cog_count} files likely already in COG format",
                'action': 'Skip COG conversion for these files',
                'files_affected': cog_count
            })
        
        # Check for tiled scenes
        tile_count = sum(1 for f in files 
                        if f.get('inferred_metadata', {}).get('part_of_tiled_scene'))
        if tile_count > 0:
            recommendations.append({
                'type': 'grouping',
                'message': f"Found {tile_count} files that are part of tiled scenes",
                'action': 'Consider creating virtual mosaics for complete scenes',
                'files_affected': tile_count
            })
        
        # Check for large files
        large_files = [f for f in files if f.get('size', 0) > 1024*1024*1024]  # >1GB
        if large_files:
            recommendations.append({
                'type': 'performance',
                'message': f"Found {len(large_files)} large files (>1GB)",
                'action': 'Use smart mode for metadata extraction',
                'files_affected': len(large_files)
            })
        
        return recommendations