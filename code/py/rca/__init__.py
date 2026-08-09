"""
RU-PlumeScan Reference Catalog Adapter (RCA).

Импорт reference catalogs (Schuit 2023, UNEP IMEO MARS, CAMS Hotspot Explorer)
в Common Plume Schema и публикация в GEE Assets.

См. Algorithm.md §9 и RNA.md §5.
"""

from rca.base_ingester import BaseIngester, ValidationError
from rca.common_schema import (
    CONFIDENCE_LEVELS,
    DETECTION_METHODS,
    EVENT_CLASSES,
    GAS_TYPES,
    MAGNITUDE_UNITS,
    SCHEMA_VERSION,
    SOURCE_CATALOGS,
    SOURCE_TYPES,
    PlumeEvent,
    from_dict,
    to_geojson_feature,
    validate_batch,
)

__all__ = [
    "BaseIngester",
    "ValidationError",
    "PlumeEvent",
    "from_dict",
    "to_geojson_feature",
    "validate_batch",
    "SCHEMA_VERSION",
    "GAS_TYPES",
    "CONFIDENCE_LEVELS",
    "EVENT_CLASSES",
    "MAGNITUDE_UNITS",
    "DETECTION_METHODS",
    "SOURCE_CATALOGS",
    "SOURCE_TYPES",
]
