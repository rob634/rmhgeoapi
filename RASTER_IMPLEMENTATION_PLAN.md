# Intelligent Raster Processing Implementation Plan

## 📋 Overview
This document outlines the implementation plan to upgrade the current raster processing system to match the intelligent workflow described in `ancient_code/raster_plan.json`. The plan bridges the gap between existing capabilities and the advanced spatial-aware processing system.

**Created**: January 24, 2025  
**Target Completion**: 3 weeks  
**Priority**: High - Critical for handling multi-TIFF scenarios efficiently

## 🎯 Goal
Transform the current file-by-file raster processing into an intelligent system that:
1. **Analyzes spatial relationships** between multiple input files
2. **Automatically selects optimal processing strategy** based on file characteristics
3. **Dynamically generates task sequences** for efficient processing
4. **Validates spatial completeness** of outputs

## 📊 Current State Assessment

### ✅ What We Have
- **Raster Processing**: Complete COG conversion, validation, reprojection
- **STAC Cataloging**: Full STAC 1.0 implementation with PostGIS
- **State Management**: Job/task tracking with two-queue architecture
- **Basic PostGIS**: Database setup with geometry support
- **Mosaic Processing**: Can merge multiple rasters

### ❌ What We're Missing
- **Spatial Analysis**: No PostGIS queries for adjacency/overlap detection
- **Strategy Classification**: No automated routing based on spatial relationships
- **Dynamic Workflows**: Fixed pipelines instead of adaptive task generation
- **STAC-First**: Processing happens before STAC registration
- **Spatial Validation**: No coverage completeness checks

## 🏗️ Implementation Phases

### Phase 1: PostGIS Spatial Analysis Foundation (Week 1)
**Objective**: Add core spatial analysis capabilities using PostGIS

#### 1.1 Create `spatial_analyzer.py`
```python
"""
Spatial analysis service for multi-raster processing decisions.
Uses PostGIS to analyze spatial relationships between STAC items.
"""

class SpatialAnalyzer:
    def __init__(self, stac_repository):
        self.stac_repo = stac_repository
        self.db = stac_repository.db
    
    def check_adjacency(self, stac_items: List[str]) -> Dict[str, Any]:
        """
        Determine if rasters are spatially adjacent.
        
        PostGIS Query:
        SELECT a.id, b.id, 
               ST_Touches(a.geometry, b.geometry) as touches,
               ST_DWithin(a.geometry, b.geometry, 0.01) as near
        FROM geo.items a, geo.items b
        WHERE a.id != b.id AND a.id = ANY($1) AND b.id = ANY($1)
        """
        pass
    
    def calculate_overlap(self, item_a: str, item_b: str) -> float:
        """
        Calculate overlap percentage between two rasters.
        
        PostGIS Query:
        SELECT ST_Area(ST_Intersection(a.geometry, b.geometry)) / 
               ST_Area(a.geometry) * 100 as overlap_pct
        FROM geo.items a, geo.items b
        WHERE a.id = $1 AND b.id = $2
        """
        pass
    
    def get_combined_extent(self, stac_items: List[str]) -> Dict:
        """
        Calculate total coverage area and bounding box.
        
        PostGIS Query:
        SELECT ST_AsGeoJSON(ST_Envelope(ST_Union(geometry))) as bbox,
               ST_Area(ST_Union(geometry)::geography) / 1000000 as area_sqkm
        FROM geo.items WHERE id = ANY($1)
        """
        pass
    
    def detect_coverage_gaps(self, stac_items: List[str]) -> List[Dict]:
        """
        Find holes in coverage between rasters.
        
        PostGIS Query:
        SELECT ST_AsGeoJSON(
            ST_Difference(
                ST_ConvexHull(ST_Collect(geometry)),
                ST_Union(geometry)
            )
        ) as gaps
        FROM geo.items WHERE id = ANY($1)
        """
        pass
    
    def classify_spatial_relationship(self, stac_items: List[str]) -> str:
        """
        Classify overall spatial relationship.
        Returns: 'adjacent' | 'overlapping' | 'scattered' | 'identical'
        """
        pass
```

#### 1.2 Extend `stac_repository.py`
Add these methods to existing STACRepository:
```python
def find_adjacent_items(self, item_id: str, distance_km: float = 1.0) -> List[Dict]:
    """Find STAC items within distance of given item."""
    
def get_items_by_bbox(self, bbox: List[float]) -> List[Dict]:
    """Get all items intersecting bounding box."""
    
def calculate_collection_coverage(self, collection_id: str) -> Dict:
    """Calculate total spatial coverage of collection."""
```

#### 1.3 Database Schema Updates
```sql
-- Add spatial indexes if not exists
CREATE INDEX IF NOT EXISTS idx_items_geometry_gist 
ON geo.items USING GIST (geometry);

-- Add materialized view for common spatial queries
CREATE MATERIALIZED VIEW geo.item_adjacency AS
SELECT a.id as item_a, b.id as item_b,
       ST_Touches(a.geometry, b.geometry) as adjacent,
       ST_Area(ST_Intersection(a.geometry, b.geometry)) as overlap_area
FROM geo.items a, geo.items b
WHERE a.id < b.id;

CREATE INDEX ON geo.item_adjacency (item_a, item_b);
```

**Deliverables**:
- Working spatial analysis service
- PostGIS spatial queries integrated
- Performance-optimized with indexes

---

### Phase 2: Strategy Classification Service (Week 1-2)
**Objective**: Intelligent routing based on file metadata and spatial relationships

#### 2.1 Create `strategy_classifier.py`
```python
"""
Classifies processing strategy based on file characteristics and spatial analysis.
"""

from enum import Enum
from typing import List, Dict, Any
from dataclasses import dataclass

class ProcessingStrategy(Enum):
    GRID_TILE = "grid_tile"           # Monster files to tiles
    KEEP_SEPARATE = "keep_separate"    # Process independently  
    MERGE_TO_SINGLE = "merge_single"   # Merge small files
    HYBRID = "hybrid"                  # Mixed approach

class SpatialRelationship(Enum):
    ADJACENT = "adjacent"
    OVERLAPPING = "overlapping"
    SCATTERED = "scattered"
    IDENTICAL = "identical"

@dataclass
class ClassificationResult:
    strategy: ProcessingStrategy
    spatial_relationship: SpatialRelationship
    parameters: Dict[str, Any]
    reasoning: str

class StrategyClassifier:
    def __init__(self, spatial_analyzer):
        self.spatial_analyzer = spatial_analyzer
        
    def classify(self, 
                 stac_items: List[Dict],
                 file_sizes: Dict[str, int]) -> ClassificationResult:
        """
        Determine optimal processing strategy.
        
        Decision Matrix:
        - Monster files (>10GB) + adjacent → GRID_TILE
        - Optimal files (500MB-4GB) + scattered → KEEP_SEPARATE
        - Small files (<500MB) + adjacent → MERGE_TO_SINGLE
        - Mixed sizes → HYBRID
        """
        
        # Analyze spatial relationships
        spatial_rel = self.spatial_analyzer.classify_spatial_relationship(
            [item['id'] for item in stac_items]
        )
        
        # Analyze file sizes
        total_size_gb = sum(file_sizes.values()) / (1024**3)
        max_size_gb = max(file_sizes.values()) / (1024**3)
        avg_size_gb = total_size_gb / len(file_sizes)
        
        # Apply classification rules
        if max_size_gb > 10 or total_size_gb > 40:
            if spatial_rel in [SpatialRelationship.ADJACENT, 
                              SpatialRelationship.OVERLAPPING]:
                return ClassificationResult(
                    strategy=ProcessingStrategy.GRID_TILE,
                    spatial_relationship=spatial_rel,
                    parameters={
                        "tile_size_km": 10,
                        "target_file_size_mb": 2000,
                        "overlap_pixels": 128
                    },
                    reasoning=f"Monster files ({max_size_gb:.1f}GB max) "
                            f"with {spatial_rel.value} relationship"
                )
        
        elif all(0.5 <= (s/(1024**3)) <= 4 for s in file_sizes.values()):
            if spatial_rel == SpatialRelationship.SCATTERED:
                return ClassificationResult(
                    strategy=ProcessingStrategy.KEEP_SEPARATE,
                    spatial_relationship=spatial_rel,
                    parameters={
                        "process_independently": True,
                        "maintain_original_bounds": True
                    },
                    reasoning="Optimal-sized files with no spatial relationship"
                )
        
        elif all(s/(1024**3) < 0.5 for s in file_sizes.values()):
            if spatial_rel in [SpatialRelationship.ADJACENT,
                              SpatialRelationship.OVERLAPPING]:
                gaps = self.spatial_analyzer.detect_coverage_gaps(
                    [item['id'] for item in stac_items]
                )
                if len(gaps) == 0 or self._gap_percentage(gaps) < 10:
                    return ClassificationResult(
                        strategy=ProcessingStrategy.MERGE_TO_SINGLE,
                        spatial_relationship=spatial_rel,
                        parameters={
                            "merge_method": "VRT_TO_COG",
                            "fill_gaps": False
                        },
                        reasoning="Small adjacent files suitable for merging"
                    )
        
        # Default to hybrid for mixed scenarios
        return ClassificationResult(
            strategy=ProcessingStrategy.HYBRID,
            spatial_relationship=spatial_rel,
            parameters={
                "group_by_proximity": True,
                "size_threshold_mb": 500
            },
            reasoning="Mixed file sizes require hybrid approach"
        )
```

#### 2.2 Extend `state_models.py`
```python
# Add to existing enums
class ProcessingStrategy(Enum):
    GRID_TILE = "grid_tile"
    KEEP_SEPARATE = "keep_separate"
    MERGE_TO_SINGLE = "merge_single"
    HYBRID = "hybrid"

class SpatialRelationship(Enum):
    ADJACENT = "adjacent"
    OVERLAPPING = "overlapping"
    SCATTERED = "scattered"
    IDENTICAL = "identical"

# Update JobRecord
@dataclass
class JobRecord:
    # ... existing fields ...
    processing_strategy: Optional[ProcessingStrategy] = None
    spatial_relationship: Optional[SpatialRelationship] = None
    strategy_parameters: Optional[Dict[str, Any]] = None
```

**Deliverables**:
- Strategy classification service
- Rules engine for decision making
- Integration with state models

---

### Phase 3: Workflow Orchestrator (Week 2)
**Objective**: Dynamic task generation based on chosen strategy

#### 3.1 Create `workflow_orchestrator.py`
```python
"""
Orchestrates dynamic task sequences based on processing strategy.
"""

from typing import List, Dict, Any
from state_models import TaskMessage, TaskType, ProcessingStrategy

class WorkflowOrchestrator:
    def __init__(self, state_manager, queue_service):
        self.state_manager = state_manager
        self.queue_service = queue_service
    
    def generate_tasks(self, 
                      job_id: str,
                      strategy: ProcessingStrategy,
                      parameters: Dict[str, Any],
                      input_files: List[str]) -> List[TaskMessage]:
        """Generate task sequence based on strategy."""
        
        if strategy == ProcessingStrategy.GRID_TILE:
            return self._generate_grid_tile_tasks(job_id, parameters, input_files)
        elif strategy == ProcessingStrategy.KEEP_SEPARATE:
            return self._generate_separate_tasks(job_id, parameters, input_files)
        elif strategy == ProcessingStrategy.MERGE_TO_SINGLE:
            return self._generate_merge_tasks(job_id, parameters, input_files)
        elif strategy == ProcessingStrategy.HYBRID:
            return self._generate_hybrid_tasks(job_id, parameters, input_files)
    
    def _generate_grid_tile_tasks(self, job_id, params, files) -> List[TaskMessage]:
        """
        Task sequence for GRID_TILE strategy:
        1. Calculate tile grid using PostGIS
        2. Process each tile in parallel
        3. Validate each tile output
        4. Update STAC collection
        """
        tasks = []
        
        # Task 1: Calculate grid
        tasks.append(TaskMessage(
            job_id=job_id,
            task_id=f"{job_id}_calculate_grid",
            task_type="CALCULATE_GRID",
            sequence_number=1,
            parameters={
                "tile_size_km": params["tile_size_km"],
                "input_files": files
            }
        ))
        
        # Tasks 2-N: Process tiles (placeholder, actual count determined at runtime)
        # These will be dynamically generated after grid calculation
        
        return tasks
    
    def _generate_separate_tasks(self, job_id, params, files) -> List[TaskMessage]:
        """
        Task sequence for KEEP_SEPARATE strategy:
        1. Validate and reproject each file
        2. Convert each to COG
        3. Validate outputs
        4. Update STAC items
        """
        tasks = []
        sequence = 1
        
        for file in files:
            # Reproject task
            tasks.append(TaskMessage(
                job_id=job_id,
                task_id=f"{job_id}_reproject_{sequence}",
                task_type="REPROJECT",
                sequence_number=sequence,
                parameters={"input_file": file, "target_crs": "EPSG:4326"}
            ))
            sequence += 1
            
            # COG conversion task
            tasks.append(TaskMessage(
                job_id=job_id,
                task_id=f"{job_id}_cog_{sequence}",
                task_type="CREATE_COG",
                sequence_number=sequence,
                parameters={"input_file": file}
            ))
            sequence += 1
        
        # Final validation
        tasks.append(TaskMessage(
            job_id=job_id,
            task_id=f"{job_id}_validate",
            task_type="VALIDATE",
            sequence_number=sequence,
            parameters={"validate_all": True}
        ))
        
        return tasks
    
    def _generate_merge_tasks(self, job_id, params, files) -> List[TaskMessage]:
        """
        Task sequence for MERGE_TO_SINGLE strategy:
        1. Validate and reproject all files
        2. Build VRT
        3. Create merged COG
        4. Validate output
        5. Update STAC
        """
        tasks = []
        sequence = 1
        
        # Reproject all files
        for file in files:
            tasks.append(TaskMessage(
                job_id=job_id,
                task_id=f"{job_id}_reproject_{sequence}",
                task_type="REPROJECT",
                sequence_number=sequence,
                parameters={"input_file": file, "target_crs": "EPSG:4326"}
            ))
            sequence += 1
        
        # Build VRT
        tasks.append(TaskMessage(
            job_id=job_id,
            task_id=f"{job_id}_build_vrt",
            task_type="BUILD_VRT",
            sequence_number=sequence,
            parameters={"input_files": files}
        ))
        sequence += 1
        
        # Create merged COG
        tasks.append(TaskMessage(
            job_id=job_id,
            task_id=f"{job_id}_merge_cog",
            task_type="CREATE_MERGED_COG",
            sequence_number=sequence,
            parameters={"merge_method": params["merge_method"]}
        ))
        sequence += 1
        
        # Validate
        tasks.append(TaskMessage(
            job_id=job_id,
            task_id=f"{job_id}_validate",
            task_type="VALIDATE",
            sequence_number=sequence,
            parameters={}
        ))
        
        return tasks
```

#### 3.2 Extend `task_router.py`
```python
# Add new task handlers
def _handle_calculate_grid(self, task: TaskMessage) -> Dict[str, Any]:
    """Calculate optimal tile grid using PostGIS."""
    from grid_generator import GridGenerator
    generator = GridGenerator()
    grid = generator.calculate_grid(
        task.parameters["input_files"],
        task.parameters["tile_size_km"]
    )
    
    # Generate tile processing tasks dynamically
    orchestrator = WorkflowOrchestrator(self.state_manager, self.queue_service)
    tile_tasks = orchestrator.generate_tile_tasks(task.job_id, grid)
    
    # Queue all tile tasks
    for tile_task in tile_tasks:
        self.queue_service.send_message("geospatial-tasks", tile_task)
    
    return {"grid_tiles": len(grid), "status": "grid_calculated"}

def _handle_build_vrt(self, task: TaskMessage) -> Dict[str, Any]:
    """Build virtual raster from multiple files."""
    from gdal import BuildVRT
    vrt_path = f"temp/{task.job_id}/mosaic.vrt"
    BuildVRT(vrt_path, task.parameters["input_files"])
    return {"vrt_path": vrt_path, "status": "vrt_created"}

def _handle_process_tile(self, task: TaskMessage) -> Dict[str, Any]:
    """Process individual tile from grid."""
    from tile_processor import TileProcessor
    processor = TileProcessor()
    result = processor.process_tile(
        task.parameters["bounds"],
        task.parameters["input_files"],
        task.parameters["output_path"]
    )
    return result
```

**Deliverables**:
- Dynamic workflow orchestration
- Task generation for each strategy
- Integration with existing task router

---

### Phase 4: STAC-First Architecture (Week 2-3)
**Objective**: Mandatory STAC registration before processing

#### 4.1 Create `stac_first_validator.py`
```python
"""
Ensures STAC registration happens before any processing.
"""

class STACFirstValidator:
    def __init__(self, stac_service, spatial_analyzer):
        self.stac_service = stac_service
        self.spatial_analyzer = spatial_analyzer
    
    def validate_and_register(self, input_files: List[str]) -> Dict[str, Any]:
        """
        Extract metadata and register in STAC before processing.
        
        Steps:
        1. Extract metadata from files (using GDAL VSI for cloud files)
        2. Create STAC items
        3. Insert to PostGIS
        4. Validate entries
        5. Return STAC IDs for processing
        """
        stac_items = []
        
        for file in input_files:
            # Extract metadata without downloading
            metadata = self._extract_metadata_vsi(file)
            
            # Create STAC item
            stac_item = self._create_stac_item(file, metadata)
            
            # Insert to database
            item_id = self.stac_service.ingest_item(stac_item)
            stac_items.append(item_id)
        
        # Validate all items inserted correctly
        validation = self._validate_stac_entries(stac_items)
        
        if not validation["passed"]:
            raise ValueError(f"STAC validation failed: {validation['errors']}")
        
        return {
            "stac_ids": stac_items,
            "validation_passed": True,
            "metadata_summary": self._summarize_metadata(stac_items)
        }
    
    def _extract_metadata_vsi(self, file_url: str) -> Dict:
        """Use GDAL VSI to read metadata without downloading."""
        import rasterio
        from rasterio.env import Env
        
        # Convert to VSI path for Azure
        vsi_path = f"/vsiaz/{file_url.replace('https://', '')}"
        
        with Env(AZURE_STORAGE_ACCOUNT=Config.STORAGE_ACCOUNT_NAME):
            with rasterio.open(vsi_path) as src:
                return {
                    "bounds": src.bounds,
                    "crs": src.crs.to_string(),
                    "resolution": src.res,
                    "count": src.count,
                    "dtype": str(src.dtypes[0]),
                    "width": src.width,
                    "height": src.height,
                    "transform": src.transform
                }
```

#### 4.2 Update Job State Flow
```python
# In state_models.py, update JobState enum
class JobState(Enum):
    INITIALIZED = "initialized"
    STAC_REGISTRATION = "stac_registration"  # NEW
    SPATIAL_ANALYSIS = "spatial_analysis"    # NEW
    STRATEGY_SELECTION = "strategy_selection" # NEW
    PLANNING = "planning"
    PROCESSING = "processing"
    VALIDATION = "validation"
    STAC_UPDATE = "stac_update"             # NEW
    COMPLETED = "completed"
    FAILED = "failed"
```

#### 4.3 Modify `function_app.py` endpoints
```python
@app.route(route="jobs/intelligent_raster", methods=["POST"])
def submit_intelligent_raster_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    New endpoint for intelligent multi-raster processing.
    
    Workflow:
    1. STAC registration (mandatory)
    2. Spatial analysis
    3. Strategy classification
    4. Dynamic task generation
    5. Processing
    6. Validation
    """
    # ... implementation ...
```

**Deliverables**:
- STAC-first validation service
- Updated job state flow
- New API endpoint for intelligent processing

---

### Phase 5: Advanced Features & Validation (Week 3)
**Objective**: Complete the intelligent processing system

#### 5.1 Create `grid_generator.py`
```python
"""
Generate optimal grids for tiling large rasters.
"""

class GridGenerator:
    def __init__(self, db_client):
        self.db = db_client
    
    def generate_square_grid(self, 
                            extent: Dict,
                            tile_size_km: float) -> List[Dict]:
        """
        Generate square grid using PostGIS.
        
        Query:
        SELECT row_number() over() as tile_id,
               ST_AsGeoJSON(geom) as geometry,
               ST_XMin(geom) as xmin,
               ST_YMin(geom) as ymin,
               ST_XMax(geom) as xmax,
               ST_YMax(geom) as ymax
        FROM ST_SquareGrid(
            $1,  -- tile_size_degrees
            ST_MakeEnvelope($2, $3, $4, $5, 4326)  -- extent
        )
        """
        pass
    
    def generate_hexagon_grid(self,
                             extent: Dict,
                             tile_size_km: float) -> List[Dict]:
        """Generate hexagonal grid for better coverage."""
        pass
```

#### 5.2 Create `spatial_validator.py`
```python
"""
Validate spatial completeness of processing outputs.
"""

class SpatialValidator:
    def __init__(self, stac_repository):
        self.stac_repo = stac_repository
    
    def validate_spatial_completeness(self,
                                     input_ids: List[str],
                                     output_ids: List[str]) -> Dict:
        """
        Ensure no data lost in processing.
        
        PostGIS Query:
        SELECT 
            ST_Equals(
                ST_Union(i.geometry),
                ST_Union(o.geometry)
            ) as spatially_complete,
            ST_Area(ST_Difference(
                ST_Union(i.geometry),
                ST_Union(o.geometry)
            )) as missing_area
        FROM 
            (SELECT geometry FROM geo.items WHERE id = ANY($1)) i,
            (SELECT geometry FROM geo.items WHERE id = ANY($2)) o
        """
        pass
    
    def validate_coverage_consistency(self,
                                     collection_id: str) -> Dict:
        """Check for gaps or overlaps in collection."""
        pass
```

**Deliverables**:
- Grid generation utilities
- Spatial validation service
- Complete intelligent processing system

---

## 📊 Success Metrics

| Phase | Success Criteria | Validation Method |
|-------|-----------------|-------------------|
| **Phase 1** | Detect adjacent/overlapping rasters | Test with Namangan tiles (known adjacent) |
| **Phase 2** | Correctly classify processing strategy | Test with various file size/spatial combinations |
| **Phase 3** | Generate appropriate task sequences | Verify task counts match strategy |
| **Phase 4** | All files in STAC before processing | Check STAC entries exist before COG tasks |
| **Phase 5** | No spatial data loss | Compare input/output coverage areas |

## 🧪 Test Scenarios

### Scenario 1: Four Adjacent Drone Images (50GB each)
- **Input**: Large drone orthophotos
- **Expected Strategy**: GRID_TILE
- **Output**: ~400 tiles of 2GB each

### Scenario 2: Four Sentinel-2 Tiles (200MB each)
- **Input**: Small adjacent satellite tiles
- **Expected Strategy**: MERGE_TO_SINGLE
- **Output**: Single 800MB COG

### Scenario 3: Mixed Maxar Delivery
- **Input**: Various sizes, some overlap
- **Expected Strategy**: HYBRID
- **Output**: Grouped by proximity

## 🚀 Implementation Checklist

### Week 1
- [ ] Create `spatial_analyzer.py`
- [ ] Add PostGIS spatial queries
- [ ] Create `strategy_classifier.py`
- [ ] Test spatial analysis with existing STAC items

### Week 2
- [ ] Create `workflow_orchestrator.py`
- [ ] Extend task router with new handlers
- [ ] Create `stac_first_validator.py`
- [ ] Update job state flow

### Week 3
- [ ] Create `grid_generator.py`
- [ ] Create `spatial_validator.py`
- [ ] Integration testing
- [ ] Production deployment

## 📝 Notes for Future Claudes

1. **Start with Phase 1** - The spatial analysis is foundational
2. **Use existing PostGIS** - Database and connection already configured
3. **Leverage state management** - Job/task tracking system is robust
4. **Test with real data** - Bronze container has good test cases
5. **Incremental deployment** - Each phase can be deployed independently

## 🔗 Related Files

- **Plan Source**: `/ancient_code/raster_plan.json`
- **Current Services**: `services.py`, `raster_processor.py`
- **State Management**: `state_manager.py`, `state_models.py`
- **STAC System**: `stac_service.py`, `stac_repository.py`
- **Database**: `database_client.py` (has PostGIS support)

## 🎯 First Step

Start by creating `spatial_analyzer.py` with the four core methods:
1. `check_adjacency()`
2. `calculate_overlap()`
3. `get_combined_extent()`
4. `detect_coverage_gaps()`

This provides the foundation for all intelligent routing decisions.