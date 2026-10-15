"""Semantic Locality & Geometry Engine (SLGE), Block A foundation.

This first block resolves already available source geometries into explicit
``DocumentedGeometry`` and ``SearchGeometry`` containers.  It intentionally
performs no DEM reconstruction and does not replace the legacy pipeline yet.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .documented_geometry import DocumentedGeometry
from .geometry_confidence import GeometryConfidenceService
from .locality_parser import SemanticLocalityParser
from .resolved_locality import LocalityInterpretation, ResolvedLocality
from .search_geometry import SearchGeometry
from .unified_geometry_strategy import UnifiedGeometryStrategyResolver


class LocalityGeometryEngine:
    SOURCE_CONFIDENCE = {
        "official_admin_polygon": 1.00,
        "official_polygon": 0.98,
        "osm_polygon": 0.92,
        "osm_line": 0.90,
        "geocoder_polygon": 0.88,
        "geocoder_bbox": 0.82,
        "dem_reconstructed": 0.72,
        "semantic_estimate": 0.60,
        "geocoder_point": 0.68,
        "osm_point": 0.82,
        "official_point": 0.92,
        "point_proxy": 0.52,
        "geocoder_line": 0.76,
        "official_line": 0.94,
        "fallback": 0.40,
        "missing": 0.0,
    }

    def __init__(self, parser: Optional[SemanticLocalityParser] = None) -> None:
        self.parser = parser or SemanticLocalityParser()
        self.confidence_service = GeometryConfidenceService()
        self.strategy_resolver = UnifiedGeometryStrategyResolver()

    @staticmethod
    def _geometry_type(geometry: Any, fallback: str = "UNKNOWN") -> str:
        if geometry is None:
            return fallback.upper()
        try:
            # QGIS geometry type: 0 point, 1 line, 2 polygon.
            geom_type = int(geometry.type())
            return {0: "POINT", 1: "LINE", 2: "POLYGON"}.get(geom_type, fallback.upper())
        except Exception:
            return fallback.upper()

    @staticmethod
    def _clone_geometry(geometry: Any) -> Any:
        if geometry is None:
            return None
        try:
            from qgis.core import QgsGeometry
            return QgsGeometry(geometry)
        except Exception:
            try:
                return geometry.clone()
            except Exception:
                return geometry

    def resolve(
        self,
        locality_text: str | None,
        municipality: str | None = None,
        *,
        source_geometry: Any = None,
        source_kind: str = "missing",
        source_identifier: Optional[str] = None,
        search_geometry: Any = None,
        search_strategy: str = "legacy_boundary",
        search_source: Optional[str] = None,
        search_metadata: Optional[Mapping[str, Any]] = None,
        geometry_method: Optional[str] = None,
        estimated: bool = False,
        requires_review: Optional[bool] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        interpretation: Optional[LocalityInterpretation] = None,
    ) -> ResolvedLocality:
        interpretation = interpretation or self.parser.parse(locality_text, municipality)
        source_kind = str(source_kind or "missing")
        strategy = self.strategy_resolver.strategy_for(
            interpretation.feature_type, interpretation.expected_geometry
        )
        confidence = self.SOURCE_CONFIDENCE.get(source_kind, self.SOURCE_CONFIDENCE["fallback"])
        documented_geom = self._clone_geometry(source_geometry)
        documented_type = self._geometry_type(documented_geom, interpretation.expected_geometry)

        if requires_review is None:
            # A point is a complete documentary representation for genuinely
            # point-like features (passes, peaks, refuges, churches).  It must
            # not be treated as a missing area or automatically penalised.
            point_complete = bool(
                strategy.point_is_valid
                and interpretation.expected_geometry == "POINT"
                and self._geometry_type(documented_geom, "UNKNOWN") == "POINT"
            )
            requires_review = bool(
                documented_geom is None
                or estimated
                or (confidence < 0.70 and not point_complete)
            )

        documented = DocumentedGeometry(
            geometry=documented_geom,
            feature_type=interpretation.feature_type,
            geometry_type=documented_type,
            source=source_kind,
            source_identifier=source_identifier,
            method=geometry_method or f"resolved_from_{source_kind}",
            confidence=confidence,
            estimated=bool(estimated),
            requires_review=bool(requires_review),
            metadata=self.strategy_resolver.enrich_metadata(
                metadata,
                feature_type=interpretation.feature_type,
                source=source_kind,
                method=geometry_method or f"resolved_from_{source_kind}",
            ),
        )

        operational_geom = self._clone_geometry(search_geometry if search_geometry is not None else source_geometry)
        search = SearchGeometry(
            geometry=operational_geom,
            strategy=search_strategy,
            source=(
                str(search_source)
                if search_source
                else ("explicit_search_geometry" if search_geometry is not None else "documented_geometry_seed")
            ),
            metadata={"slge_block": "A", **dict(search_metadata or {})},
        )

        warnings: list[str] = list(interpretation.warnings)
        if documented_geom is None:
            warnings.append("Geometria documentale non disponibile")
        if operational_geom is None:
            warnings.append("Geometria di ricerca non disponibile")
        if documented_type != interpretation.expected_geometry and interpretation.expected_geometry not in {"UNKNOWN", "ADMIN"}:
            warnings.append(
                f"Geometria disponibile {documented_type}, attesa {interpretation.expected_geometry}"
            )

        gci = self.confidence_service.calculate(
            source_kind=source_kind,
            documented_geometry=documented_geom,
            actual_geometry_type=documented_type,
            expected_geometry_type=interpretation.expected_geometry,
            semantic_confidence=interpretation.confidence,
            estimated=bool(estimated),
            requires_review=bool(requires_review),
        )

        return ResolvedLocality(
            interpretation=interpretation,
            documented_geometry=documented,
            search_geometry=search,
            geometry_confidence=gci.score,
            geometry_confidence_class=gci.confidence_class,
            geometry_confidence_reasons=gci.reasons,
            provenance={
                "engine": "GeoLichen Semantic Locality & Geometry Engine",
                "version": "SLGE-U.1",
                "unified_strategy": strategy.feature_type,
                "fallback_mode": strategy.fallback_mode,
                "source_kind": source_kind,
                "source_identifier": source_identifier,
                "gci_components": dict(gci.components),
            },
            warnings=warnings,
        )

    def resolve_from_feature(
        self,
        locality_text: str | None,
        feature: Mapping[str, Any],
        municipality: str | None = None,
        *,
        geometry_factory: Optional[Callable[[Mapping[str, Any]], Any]] = None,
        search_geometry: Any = None,
        search_strategy: str = "legacy_boundary",
    ) -> ResolvedLocality:
        """Resolve a geocoder feature without coupling Block A to one provider.

        ``geometry_factory`` may convert the feature into a ``QgsGeometry``.
        Without it, a geometry already stored under ``geometry`` is used.
        """
        source_geometry = geometry_factory(feature) if geometry_factory else feature.get("geometry")
        source_kind = str(feature.get("_geolichen_geometry_source") or feature.get("source_kind") or "geocoder_bbox")
        source_identifier = feature.get("id") or feature.get("place_id")
        return self.resolve(
            locality_text,
            municipality,
            source_geometry=source_geometry,
            source_kind=source_kind,
            source_identifier=str(source_identifier) if source_identifier is not None else None,
            search_geometry=search_geometry,
            search_strategy=search_strategy,
            estimated=bool(feature.get("_geolichen_geometry_estimated", False)),
            metadata={"provider": feature.get("provider"), "place_name": feature.get("place_name")},
        )
