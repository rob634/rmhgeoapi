"""
Pydantic models for band mapping with automatic JSON string key → int conversion.

Handles the fact that JSON only supports string keys, but Python/rasterio needs integer band indices.
"""

from typing import Dict
from pydantic import BaseModel, field_validator, ConfigDict


class BandNames(BaseModel):
    """
    Band index → name mapping with automatic string→int key conversion.

    JSON input: {"5": "Red", "3": "Green", "2": "Blue"}
    Python output: {5: "Red", 3: "Green", 2: "Blue"}

    Examples:
        >>> # From JSON (string keys)
        >>> bands = BandNames(mapping={"5": "Red", "3": "Green", "2": "Blue"})
        >>> bands.mapping
        {5: 'Red', 3: 'Green', 2: 'Blue'}

        >>> # Already int keys (no conversion needed)
        >>> bands = BandNames(mapping={5: "Red", 3: "Green", 2: "Blue"})
        >>> bands.mapping
        {5: 'Red', 3: 'Green', 2: 'Blue'}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"5": "Red", "3": "Green", "2": "Blue"}
        }
    )

    mapping: Dict[int, str]

    @field_validator('mapping', mode='before')
    @classmethod
    def convert_string_keys_to_int(cls, v):
        """
        Convert JSON string keys to integer band indices.

        Validates:
        - Input is a dict
        - Keys can be converted to integers
        - Keys are >= 1 (rasterio uses 1-based indexing)
        - Values are strings
        """
        if not isinstance(v, dict):
            raise ValueError("band_names must be a dict, e.g., {'5': 'Red', '3': 'Green', '2': 'Blue'}")

        if not v:  # Empty dict
            raise ValueError("band_names cannot be empty - must specify at least one band")

        converted = {}
        for k, v_item in v.items():
            # Validate value is string
            if not isinstance(v_item, str):
                raise ValueError(f"Band name must be string, got {type(v_item).__name__} for key '{k}'")

            # Convert key to int
            try:
                idx = int(k)
            except (ValueError, TypeError):
                raise ValueError(f"Band index '{k}' must be numeric (integer as string or int)")

            # Validate index is positive (rasterio uses 1-based indexing)
            if idx < 1:
                raise ValueError(f"Band index {idx} must be >= 1 (rasterio uses 1-based indexing)")

            converted[idx] = v_item

        return converted

    @property
    def indices(self) -> list[int]:
        """Get sorted list of band indices."""
        return sorted(self.mapping.keys())

    @property
    def count(self) -> int:
        """Get number of bands."""
        return len(self.mapping)

    def get_name(self, index: int) -> str:
        """Get band name by index."""
        return self.mapping.get(index, f"Band {index}")

    def __len__(self):
        """Support len(band_names)."""
        return len(self.mapping)

    def __iter__(self):
        """Iterate over band indices (sorted)."""
        return iter(self.indices)


# Predefined common band mappings
WORLDVIEW2_RGB = BandNames(mapping={5: "Red", 3: "Green", 2: "Blue"})
WORLDVIEW2_ALL = BandNames(mapping={
    1: "Coastal",
    2: "Blue",
    3: "Green",
    4: "Yellow",
    5: "Red",
    6: "RedEdge",
    7: "NIR1",
    8: "NIR2"
})

SENTINEL2_RGB = BandNames(mapping={4: "Red", 3: "Green", 2: "Blue"})
LANDSAT_RGB = BandNames(mapping={4: "Red", 3: "Green", 2: "Blue"})
