"""GeoLichen Semantic Locality & Geometry Engine core models (Phase 12, Block A)."""

from .documented_geometry import DocumentedGeometry
from .geometry_confidence import GeometryConfidenceResult, GeometryConfidenceService
from .locality_geometry_engine import LocalityGeometryEngine
from .locality_parser import SemanticLocalityParser
from .resolved_locality import LocalityInterpretation, ResolvedLocality
from .search_geometry import SearchGeometry
from .terrain_context import TerrainContext, TerrainRasterGrid
from .terrain_engine import TerrainPreparationEngine
from .summit_context import SummitCandidate, SummitDetectionResult
from .summit_detection_engine import SummitDetectionEngine
from .terrain_polygon_context import TerrainPolygonResult
from .terrain_polygon_engine import TerrainPolygonReconstructionEngine
from .terrain_geometry_validation_context import TerrainGeometryCheck, TerrainGeometryValidationResult
from .terrain_geometry_validation_engine import TerrainGeometryValidationEngine
from .terrain_geometry_decision_context import TerrainGeometryDecision, TerrainGeometryDecisionResult
from .terrain_geometry_decision_engine import TerrainGeometryDecisionEngine

__all__ = [
    "DocumentedGeometry",
    "GeometryConfidenceResult",
    "GeometryConfidenceService",
    "LocalityGeometryEngine",
    "LocalityInterpretation",
    "ResolvedLocality",
    "SearchGeometry",
    "SemanticLocalityParser",
    "TerrainContext",
    "TerrainRasterGrid",
    "TerrainPreparationEngine",
    "SummitCandidate",
    "SummitDetectionResult",
    "SummitDetectionEngine",
    "TerrainPolygonResult",
    "TerrainPolygonReconstructionEngine",
    "TerrainGeometryCheck",
    "TerrainGeometryValidationResult",
    "TerrainGeometryValidationEngine",
    "TerrainGeometryDecision",
    "TerrainGeometryDecisionResult",
    "TerrainGeometryDecisionEngine",
]

# Phase 13D.3 terrain/SLGE integration
from .terrain_documented_geometry_integrator import (
    TerrainDocumentedGeometryIntegrator,
    TerrainGeometryIntegrationResult,
)
