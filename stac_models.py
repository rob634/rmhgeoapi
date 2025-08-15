"""
STAC (SpatioTemporal Asset Catalog) data models
Implements STAC specification v1.0.0 standard attributes
"""
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from constants import APIParams


@dataclass
class STACBoundingBox:
    """STAC Bounding Box (bbox) - [west, south, east, north]"""
    west: float
    south: float  
    east: float
    north: float
    
    def to_list(self) -> List[float]:
        """Convert to STAC bbox array format"""
        return [self.west, self.south, self.east, self.north]
    
    @classmethod
    def from_list(cls, bbox: List[float]) -> 'STACBoundingBox':
        """Create from STAC bbox array"""
        return cls(west=bbox[0], south=bbox[1], east=bbox[2], north=bbox[3])


@dataclass
class STACGeometry:
    """STAC Geometry (GeoJSON geometry)"""
    type: str  # "Point", "Polygon", etc.
    coordinates: List[Any]  # GeoJSON coordinates
    
    def to_dict(self) -> Dict:
        """Convert to GeoJSON geometry format"""
        return {"type": self.type, "coordinates": self.coordinates}


@dataclass
class STACAsset:
    """STAC Asset - represents a file associated with an item"""
    href: str  # URL to the asset
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None  # Media type (e.g., "image/tiff")
    roles: Optional[List[str]] = None  # ["data", "thumbnail", "metadata"]
    
    def to_dict(self) -> Dict:
        """Convert to STAC asset format"""
        result = {"href": self.href}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if self.type:
            result["type"] = self.type
        if self.roles:
            result["roles"] = self.roles
        return result


@dataclass 
class STACLink:
    """STAC Link - relationship to other resources"""
    rel: str  # Relationship type ("self", "parent", "collection", etc.)
    href: str  # URL to the linked resource
    type: Optional[str] = None  # Media type
    title: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to STAC link format"""
        result = {"rel": self.rel, "href": self.href}
        if self.type:
            result["type"] = self.type
        if self.title:
            result["title"] = self.title
        return result


class STACCollection:
    """STAC Collection - groups of related items"""
    
    def __init__(self, id: str, title: str, description: str):
        self.id = id
        self.type = "Collection"  # STAC type
        self.stac_version = "1.0.0"
        self.title = title
        self.description = description
        self.keywords: List[str] = []
        self.license = "proprietary"  # Default
        self.providers: List[Dict] = []
        self.extent: Dict = {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},  # Default global
            "temporal": {"interval": [[None, None]]}  # Open-ended
        }
        self.summaries: Dict = {}
        self.links: List[STACLink] = []
        self.assets: Dict[str, STACAsset] = {}
        
        # Table Storage fields
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.item_count = 0
    
    def add_spatial_extent(self, bbox: STACBoundingBox):
        """Add spatial extent to collection"""
        self.extent["spatial"]["bbox"] = [bbox.to_list()]
    
    def add_temporal_extent(self, start: Optional[str], end: Optional[str]):
        """Add temporal extent to collection"""
        self.extent["temporal"]["interval"] = [[start, end]]
    
    def to_table_entity(self) -> Dict:
        """Convert to Table Storage entity format"""
        return {
            'PartitionKey': 'collections',
            'RowKey': self.id,
            'id': self.id,
            'type': self.type,
            'stac_version': self.stac_version,
            'title': self.title,
            'description': self.description,
            'license': self.license,
            'keywords': json.dumps(self.keywords),
            'extent': json.dumps(self.extent),
            'summaries': json.dumps(self.summaries),
            'links': json.dumps([link.to_dict() for link in self.links]),
            'assets': json.dumps({k: v.to_dict() for k, v in self.assets.items()}),
            'providers': json.dumps(self.providers),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'item_count': self.item_count
        }
    
    def to_stac_dict(self) -> Dict:
        """Convert to STAC JSON format"""
        return {
            "id": self.id,
            "type": self.type,
            "stac_version": self.stac_version,
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "license": self.license,
            "providers": self.providers,
            "extent": self.extent,
            "summaries": self.summaries,
            "links": [link.to_dict() for link in self.links],
            "assets": {k: v.to_dict() for k, v in self.assets.items()}
        }
    
    @classmethod
    def from_table_entity(cls, entity: Dict) -> 'STACCollection':
        """Create from Table Storage entity"""
        collection = cls(
            id=entity['id'],
            title=entity['title'], 
            description=entity['description']
        )
        collection.type = entity.get('type', 'Collection')
        collection.stac_version = entity.get('stac_version', '1.0.0')
        collection.license = entity.get('license', 'proprietary')
        collection.created_at = entity.get('created_at')
        collection.updated_at = entity.get('updated_at')
        collection.item_count = entity.get('item_count', 0)
        
        # Parse JSON fields
        if entity.get('keywords'):
            collection.keywords = json.loads(entity['keywords'])
        if entity.get('extent'):
            collection.extent = json.loads(entity['extent'])
        if entity.get('summaries'):
            collection.summaries = json.loads(entity['summaries'])
        if entity.get('providers'):
            collection.providers = json.loads(entity['providers'])
        
        # Parse links and assets
        if entity.get('links'):
            links_data = json.loads(entity['links'])
            collection.links = [STACLink(**link) for link in links_data]
        if entity.get('assets'):
            assets_data = json.loads(entity['assets'])
            collection.assets = {k: STACAsset(**v) for k, v in assets_data.items()}
        
        return collection


class STACItem:
    """STAC Item - represents a single spatiotemporal asset"""
    
    def __init__(self, id: str, collection_id: str, geometry: STACGeometry, 
                 bbox: STACBoundingBox, datetime_str: str, properties: Dict):
        self.id = id
        self.type = "Feature"  # GeoJSON type
        self.stac_version = "1.0.0"
        self.collection = collection_id
        self.geometry = geometry
        self.bbox = bbox
        self.datetime = datetime_str  # ISO 8601 string
        self.properties = properties or {}
        self.assets: Dict[str, STACAsset] = {}
        self.links: List[STACLink] = []
        
        # Table Storage fields
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        
        # Generate spatial index for efficient queries
        self.spatial_index = self._generate_spatial_index()
    
    def _generate_spatial_index(self) -> str:
        """Generate spatial index for partitioning (simple grid-based)"""
        # Simple 1-degree grid for demonstration
        # In production, consider H3 or S2 indexing
        center_lon = (self.bbox.west + self.bbox.east) / 2
        center_lat = (self.bbox.south + self.bbox.north) / 2
        
        grid_lon = int(center_lon)
        grid_lat = int(center_lat)
        
        return f"{grid_lat}_{grid_lon}"
    
    def add_asset(self, key: str, asset: STACAsset):
        """Add an asset to the item"""
        self.assets[key] = asset
    
    def to_table_entity(self) -> Dict:
        """Convert to Table Storage entity format"""
        return {
            'PartitionKey': f"{self.collection}_{self.spatial_index}",  # Spatial partitioning
            'RowKey': self.id,
            'id': self.id,
            'type': self.type,
            'stac_version': self.stac_version,
            'collection': self.collection,
            'datetime': self.datetime,
            'geometry': json.dumps(self.geometry.to_dict()),
            'bbox': json.dumps(self.bbox.to_list()),
            'properties': json.dumps(self.properties),
            'assets': json.dumps({k: v.to_dict() for k, v in self.assets.items()}),
            'links': json.dumps([link.to_dict() for link in self.links]),
            'spatial_index': self.spatial_index,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    def to_stac_dict(self) -> Dict:
        """Convert to STAC JSON format"""
        return {
            "id": self.id,
            "type": self.type,
            "stac_version": self.stac_version,
            "collection": self.collection,
            "geometry": self.geometry.to_dict(),
            "bbox": self.bbox.to_list(),
            "properties": {
                "datetime": self.datetime,
                **self.properties
            },
            "assets": {k: v.to_dict() for k, v in self.assets.items()},
            "links": [link.to_dict() for link in self.links]
        }
    
    @classmethod
    def from_table_entity(cls, entity: Dict) -> 'STACItem':
        """Create from Table Storage entity"""
        # Parse geometry and bbox
        geometry_data = json.loads(entity['geometry'])
        geometry = STACGeometry(
            type=geometry_data['type'],
            coordinates=geometry_data['coordinates']
        )
        
        bbox_data = json.loads(entity['bbox'])
        bbox = STACBoundingBox.from_list(bbox_data)
        
        # Parse properties
        properties = json.loads(entity['properties'])
        
        # Create item
        item = cls(
            id=entity['id'],
            collection_id=entity['collection'],
            geometry=geometry,
            bbox=bbox,
            datetime_str=entity['datetime'],
            properties=properties
        )
        
        item.type = entity.get('type', 'Feature')
        item.stac_version = entity.get('stac_version', '1.0.0')
        item.created_at = entity.get('created_at')
        item.updated_at = entity.get('updated_at')
        item.spatial_index = entity.get('spatial_index')
        
        # Parse assets and links
        if entity.get('assets'):
            assets_data = json.loads(entity['assets'])
            item.assets = {k: STACAsset(**v) for k, v in assets_data.items()}
        if entity.get('links'):
            links_data = json.loads(entity['links'])
            item.links = [STACLink(**link) for link in links_data]
        
        return item


# STAC Query Models
@dataclass
class STACQuery:
    """STAC search query parameters"""
    collections: Optional[List[str]] = None
    bbox: Optional[STACBoundingBox] = None
    datetime: Optional[str] = None  # ISO 8601 interval
    limit: int = 10
    offset: int = 0
    ids: Optional[List[str]] = None
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate query parameters"""
        if self.limit > 1000:
            return False, "Limit cannot exceed 1000"
        if self.limit < 1:
            return False, "Limit must be at least 1"
        if self.offset < 0:
            return False, "Offset cannot be negative"
        return True, None