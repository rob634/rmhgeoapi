"""
H3 Base Grid Generation - ABC Models for Type Safety

Defines abstract interfaces and concrete models for H3 base grid generation.
Uses ABC (Abstract Base Class) pattern to enforce method signatures.

Author: Robert and Geospatial Claude Legion
Date: 15 OCT 2025
"""

from abc import ABC, abstractmethod
from typing import Protocol, Optional, Literal
from pydantic import BaseModel, Field, field_validator
import pandas as pd


# ==============================================================================
# ENUMS & LITERALS
# ==============================================================================

H3Resolution = Literal[0, 1, 2, 3, 4]
"""Valid H3 resolutions for base grid generation (0-4)"""


# ==============================================================================
# PYDANTIC MODELS - Input/Output Data Contracts
# ==============================================================================

class H3BaseGridRequest(BaseModel):
    """
    Request parameters for H3 base grid generation.

    Core Machine Contract: This model defines what the API accepts.
    """
    resolution: H3Resolution = Field(
        ...,
        description="H3 resolution level (0=coarsest ~1000km, 4=~17km edge length)"
    )

    exclude_antimeridian: bool = Field(
        default=True,
        description="If True, exclude cells crossing 180° longitude"
    )

    output_folder: str = Field(
        default="h3/base",
        description="Output folder in gold container"
    )

    output_filename: Optional[str] = Field(
        default=None,
        description="Output filename (auto-generated if not provided)"
    )

    @field_validator('output_filename')
    @classmethod
    def validate_filename(cls, v: Optional[str]) -> Optional[str]:
        """Ensure filename ends with .parquet if provided"""
        if v and not v.endswith('.parquet'):
            raise ValueError("output_filename must end with .parquet")
        return v

    def get_output_filename(self) -> str:
        """Get output filename, auto-generating if not provided"""
        if self.output_filename:
            return self.output_filename
        antimeridian_suffix = "_no_antimeridian" if self.exclude_antimeridian else ""
        return f"h3_res{self.resolution}_global{antimeridian_suffix}.parquet"


class H3BaseGridResponse(BaseModel):
    """
    Response from H3 base grid generation.

    Core Machine Contract: This model defines what the handler returns.
    """
    success: bool
    resolution: int
    total_cells: int
    antimeridian_cells_excluded: int
    blob_path: str
    file_size_mb: float
    processing_time_seconds: float

    # Grid statistics
    min_h3_index: int
    max_h3_index: int
    memory_mb: float


class H3GridStats(BaseModel):
    """Statistics about an H3 grid DataFrame"""
    cell_count: int
    resolution: Optional[int]
    memory_mb: float
    has_geometry: bool
    min_h3_index: Optional[int] = None
    max_h3_index: Optional[int] = None


# ==============================================================================
# ABSTRACT BASE CLASS - Service Interface
# ==============================================================================

class H3BaseGridService(ABC):
    """
    Abstract interface for H3 base grid generation service.

    Core Machine Contract: All implementations must provide these methods
    with exact signatures.
    """

    @abstractmethod
    def generate_grid(
        self,
        resolution: H3Resolution,
        exclude_antimeridian: bool = True
    ) -> pd.DataFrame:
        """
        Generate complete H3 grid at specified resolution.

        Args:
            resolution: H3 resolution level (0-4)
            exclude_antimeridian: If True, filter out cells crossing 180° longitude

        Returns:
            DataFrame with columns: h3_index, geometry_wkt, resolution, is_valid

        Raises:
            ValueError: If resolution is invalid
            RuntimeError: If grid generation fails
        """
        pass

    @abstractmethod
    def save_grid(
        self,
        df: pd.DataFrame,
        filename: str,
        folder: str
    ) -> str:
        """
        Save H3 grid to gold container as GeoParquet.

        Args:
            df: Grid DataFrame to save
            filename: Output filename (must end with .parquet)
            folder: Folder path in gold container

        Returns:
            Full blob path where grid was saved

        Raises:
            ValueError: If filename is invalid
            RuntimeError: If save operation fails
        """
        pass

    @abstractmethod
    def get_grid_stats(self, df: pd.DataFrame) -> H3GridStats:
        """
        Calculate statistics for an H3 grid.

        Args:
            df: Grid DataFrame

        Returns:
            Grid statistics model
        """
        pass


# ==============================================================================
# PROTOCOL - Duck-Typed Handler Interface
# ==============================================================================

class H3BaseGridHandler(Protocol):
    """
    Protocol defining the handler function signature.

    Core Machine Contract: Handlers must match this signature exactly.
    """

    def __call__(self, task_params: dict) -> dict:
        """
        Execute H3 base grid generation task.

        Args:
            task_params: Task parameters dict (will be validated against H3BaseGridRequest)

        Returns:
            Result dict matching H3BaseGridResponse schema
        """
        ...


# ==============================================================================
# EXPECTED CELL COUNTS BY RESOLUTION
# ==============================================================================

EXPECTED_CELL_COUNTS = {
    0: {
        "total": 122,
        "description": "122 base cells (110 hexagons + 12 pentagons)",
        "avg_area_km2": 4250000,
        "avg_edge_km": 1108
    },
    1: {
        "total": 842,
        "description": "~842 cells globally",
        "avg_area_km2": 607000,
        "avg_edge_km": 418
    },
    2: {
        "total": 5882,
        "description": "~5,882 cells globally",
        "avg_area_km2": 86745,
        "avg_edge_km": 158
    },
    3: {
        "total": 41162,
        "description": "~41,162 cells globally",
        "avg_area_km2": 12392,
        "avg_edge_km": 59.8
    },
    4: {
        "total": 288122,
        "description": "~288,122 cells globally",
        "avg_area_km2": 1770,
        "avg_edge_km": 22.6
    }
}
"""
Expected cell counts for each H3 resolution level.
Actual counts may vary slightly due to antimeridian filtering.
"""
