from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject, QgsRectangle

from ..core.locality_geometry_engine import LocalityGeometryEngine
from ..core.unified_geometry_strategy import UnifiedGeometryStrategyResolver
from .semantic_search_buffer_service import SemanticSearchBufferService
from .adaptive_buffer_decision_service import AdaptiveBufferDecisionService
from .adaptive_search_geometry_engine import AdaptiveSearchGeometryEngine
from .osm_search_geometry_service import OsmSearchGeometryService
from .search_geometry_resolution_service import SearchGeometryResolutionService
from ..core.geometry_resolution_engine import GeometryResolutionEngine
from ..core.geometry_result import GeometryResult
from ..core.geometry_context import GeoreferencingGeometryContext
from ..core.geometry_provenance import GeometryProvenance
from ._shared_geo_utils import local_metric_crs


class InitialBoundaryService:
    """Compatibility facade backed by the Semantic Locality & Geometry Engine.

    From Phase 12 Block B this service no longer returns two unrelated
    geometries assembled ad hoc. It creates one ``ResolvedLocality`` and only
    exposes legacy dictionary keys for callers not migrated yet.
    """

    def __init__(self, geometry_engine=None):
        self.geometry_engine = geometry_engine or LocalityGeometryEngine()
        self.strategy_resolver = UnifiedGeometryStrategyResolver()
        self.geometry_resolution_engine = GeometryResolutionEngine()
        self.adaptive_buffer_decision_service = AdaptiveBufferDecisionService()
        self.search_buffer_service = SemanticSearchBufferService()
        self.adaptive_search_geometry_engine = AdaptiveSearchGeometryEngine(self.search_buffer_service)
        self.osm_search_geometry_service = OsmSearchGeometryService()
        self.search_geometry_resolution_service = SearchGeometryResolutionService()

    # Legacy compatibility view. Authoritative values are defined in
    # SemanticSearchBufferService and are selected by semantic locality type.
    DEFAULT_BUFFERS = {
        "municipality": None,
        "valley": 1500,
        "pass": 250,
        "summit": 150,
        "summit_peak": 150,
        "hill": 500,
        "mountain_area": 1000,
        "mountain_group": 2500,
        "meadow": 600,
        "forest_area": 1000,
        "refuge_malga": 150,
        "hydro": 300,
        "trail": 150,
        "nearby_place": 500,
        "generic_toponym": 500,
        "locality": 500,
    }


    # Documentary fallback radii used only when the locality is explicitly
    # area-like but the geocoder supplies no usable area (or a point-sized
    # bbox). They represent an estimated geographic extent, remain separate
    # from the operational search extent and are flagged for manual review.
    DOCUMENTED_FALLBACK_RADII = {
        "valley": 2000.0,
        "mountain_area": 800.0,
        "mountain_group": 2000.0,
        "forest_area": 1000.0,
        "hydro": 300.0,
    }

    # A bbox smaller than this is generally a cartographic point envelope,
    # not a defensible area geometry for an area-like locality.
    MIN_DOCUMENTED_AREA_DIM_M = 100.0


    @staticmethod
    def _geometry_type_name(geometry):
        if geometry is None:
            return "NONE"
        try:
            if geometry.isEmpty():
                return "EMPTY"
            return {0: "POINT", 1: "LINE", 2: "POLYGON"}.get(int(geometry.type()), "UNKNOWN")
        except Exception:
            return "UNKNOWN"

    def _administrative_geometry_diagnostics(
        self, *, feature, ref_type, semantic_type, interpretation, bbox_geom,
        documented, documented_source, search_resolution, search, search_strategy,
        osm_search_result, locality_text, municipality
    ):
        """Return a serialisable trace of municipality geometry resolution.

        Phase 15.3.4 is diagnostic only: it explains every available input and
        decision without changing the selected DocumentedGeometry or
        SearchGeometry.
        """
        canonical = self.search_buffer_service.canonical_type(
            getattr(interpretation, "feature_type", None) or semantic_type or ref_type
        )
        relevant = bool(
            canonical == "municipality"
            or str(ref_type or "").lower() == "municipality"
            or str(getattr(interpretation, "expected_geometry", "") or "").upper() == "ADMIN"
        )
        if not relevant:
            return {"active": False}

        bbox_w, bbox_h = self._bbox_size_m(bbox_geom)
        osm = osm_search_result
        osm_tags = dict(getattr(osm, "tags", {}) or {}) if osm is not None else {}
        osm_success = bool(getattr(osm, "success", False)) if osm is not None else False
        osm_geom_type = str(getattr(osm, "geometry_type", "") or "") if osm is not None else ""
        osm_admin_compatible = bool(
            osm_success
            and osm_geom_type.upper() == "POLYGON"
            and osm_tags.get("boundary") == "administrative"
        )
        final_type = self._geometry_type_name(search)
        documented_type = self._geometry_type_name(documented)

        reasons = []
        if bbox_geom is None or bbox_geom.isEmpty():
            reasons.append("geocoder_bbox_missing")
        else:
            reasons.append("geocoder_bbox_available")
        if osm is None:
            reasons.append("osm_lookup_no_result_object")
        elif not osm_success:
            reasons.append("osm_lookup_failed")
        elif not osm_admin_compatible:
            reasons.append("osm_result_not_compatible_administrative_polygon")
        else:
            reasons.append("osm_administrative_polygon_available")
        if bool(search_resolution.used_fallback):
            reasons.append("semantic_fallback_used")
        if str(search_strategy or "").startswith("municipality_point_fallback"):
            reasons.append("municipality_reduced_to_point_buffer")
        if documented is None:
            reasons.append("documented_administrative_geometry_missing")

        return {
            "active": True,
            "phase": "15.3.4",
            "requested_municipality": str(municipality or locality_text or ""),
            "locality_text": str(locality_text or ""),
            "reference_type": str(ref_type or ""),
            "semantic_type": str(semantic_type or ""),
            "canonical_type": str(canonical or ""),
            "expected_geometry": str(getattr(interpretation, "expected_geometry", "") or ""),
            "matched_rule": str(getattr(interpretation, "matched_rule", "") or ""),
            "official_layer_lookup_implemented": False,
            "official_layer_lookup_status": "not_available_in_initial_boundary_service",
            "geocoder_provider": str(feature.get("provider") or "") if isinstance(feature, dict) else "",
            "geocoder_place_name": str(feature.get("place_name") or feature.get("text") or "") if isinstance(feature, dict) else "",
            "geocoder_feature_id": str(feature.get("id") or feature.get("place_id") or "") if isinstance(feature, dict) else "",
            "geocoder_bbox_available": bool(bbox_geom is not None and not bbox_geom.isEmpty()),
            "geocoder_bbox_width_m": bbox_w,
            "geocoder_bbox_height_m": bbox_h,
            "documented_geometry_source": str(documented_source or ""),
            "documented_geometry_type": documented_type,
            "osm_lookup_attempted": True,
            "osm_lookup_success": osm_success,
            "osm_error": str(getattr(osm, "error", "") or (search_resolution.metadata or {}).get("osm_error") or "") if osm is not None else str((search_resolution.metadata or {}).get("osm_error") or ""),
            "osm_endpoint": str(getattr(osm, "endpoint", "") or "") if osm is not None else "",
            "osm_from_cache": bool(getattr(osm, "from_cache", False)) if osm is not None else False,
            "osm_geometry_type": osm_geom_type,
            "osm_object_type": str(getattr(osm, "osm_type", "") or "") if osm is not None else "",
            "osm_id": int(getattr(osm, "osm_id", 0) or 0) if osm is not None else 0,
            "osm_name": str(getattr(osm, "name", "") or "") if osm is not None else "",
            "osm_boundary_tag": str(osm_tags.get("boundary") or ""),
            "osm_admin_level": str(osm_tags.get("admin_level") or ""),
            "osm_match_score": float(getattr(osm, "match_score", 0.0) or 0.0) if osm is not None else 0.0,
            "osm_anchor_distance_m": getattr(osm, "anchor_distance_m", None) if osm is not None else None,
            "osm_administrative_polygon_compatible": osm_admin_compatible,
            "resolution_source": str(search_resolution.source or ""),
            "fallback_used": bool(search_resolution.used_fallback),
            "search_strategy": str(search_strategy or ""),
            "final_search_geometry_type": final_type,
            "reasons": reasons,
        }

    def _point_from_feature(self, feature):
        """Extract a representative WGS84 point from common geocoder payloads."""
        if not isinstance(feature, dict):
            return None
        center = feature.get("center")
        if center and len(center) >= 2:
            return QgsGeometry.fromPointXY(QgsPointXY(float(center[0]), float(center[1])))

        geometry = feature.get("geometry")
        if isinstance(geometry, dict):
            coords = geometry.get("coordinates")
            geom_type = str(geometry.get("type") or "").lower()
            if geom_type == "point" and coords and len(coords) >= 2:
                return QgsGeometry.fromPointXY(QgsPointXY(float(coords[0]), float(coords[1])))

        lon = feature.get("lon", feature.get("longitude", feature.get("x")))
        lat = feature.get("lat", feature.get("latitude", feature.get("y")))
        if lon is not None and lat is not None:
            try:
                return QgsGeometry.fromPointXY(QgsPointXY(float(lon), float(lat)))
            except Exception:
                pass

        bbox = feature.get("bbox")
        if bbox and len(bbox) == 4:
            cx = (float(bbox[0]) + float(bbox[2])) / 2.0
            cy = (float(bbox[1]) + float(bbox[3])) / 2.0
            return QgsGeometry.fromPointXY(QgsPointXY(cx, cy))
        return None

    def feature_to_geometry(self, feature):
        if feature is None:
            return None
        bbox = feature.get("bbox") if isinstance(feature, dict) else None
        if bbox and len(bbox) == 4:
            return QgsGeometry.fromRect(QgsRectangle(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
        return self._point_from_feature(feature)

    def _metric_buffer_in_wgs84(self, geometry_wgs84, meters):
        """Crea un buffer in metri reali usando la zona UTM locale.

        EPSG:3857 non conserva la scala al suolo e alla latitudine della
        Val Camonica riduceva i raggi reali di circa il 30%. Il CRS metrico
        viene ora scelto dal centro della geometria, come per buffer manuale
        e griglia dei candidati.
        """
        if geometry_wgs84 is None or geometry_wgs84.isEmpty():
            return geometry_wgs84
        src = QgsCoordinateReferenceSystem("EPSG:4326")
        center = geometry_wgs84.centroid().asPoint()
        dst = local_metric_crs(center)
        project = QgsProject.instance()
        fwd = QgsCoordinateTransform(src, dst, project)
        rev = QgsCoordinateTransform(dst, src, project)
        geom_metric = QgsGeometry(geometry_wgs84)
        geom_metric.transform(fwd)
        buffered = geom_metric.buffer(float(meters), 48)
        buffered.transform(rev)
        return buffered


    AREA_LIKE_TYPES = {
        "forest_area",
        "valley",
        "hydro",
        "municipality",
        "mountain_area",
        "mountain_group",
    }

    def _expand_rect_wgs84(self, geom_wgs84, meters):
        """Espande una geometria/bbox in metri, tornando in WGS84."""
        if geom_wgs84 is None or geom_wgs84.isEmpty():
            return geom_wgs84
        if not meters or meters <= 0:
            return geom_wgs84
        return self._metric_buffer_in_wgs84(geom_wgs84, meters)


    def _bbox_size_m(self, geom_wgs84):
        """Ritorna larghezza/altezza bbox in metri circa."""
        try:
            if geom_wgs84 is None or geom_wgs84.isEmpty():
                return None, None
            src = QgsCoordinateReferenceSystem("EPSG:4326")
            center = geom_wgs84.centroid().asPoint()
            dst = local_metric_crs(center)
            project = QgsProject.instance()
            g = QgsGeometry(geom_wgs84)
            g.transform(QgsCoordinateTransform(src, dst, project))
            r = g.boundingBox()
            return float(r.width()), float(r.height())
        except Exception:
            return None, None


    def _semantic_type_from_feature(self, feature, ref_type=None):
        """Riconosce se il risultato rappresenta un'area reale."""
        txt = ""
        try:
            txt = " ".join([
                str(feature.get("place_name") or ""),
                str(feature.get("text") or ""),
                str(feature.get("_geolichen_ref_type") or ""),
                str(ref_type or ""),
            ]).lower()
        except Exception:
            txt = str(ref_type or "").lower()

        if any(k in txt for k in ["foresta", "bosco", "selva", "ersaf", "demaniale"]):
            return "forest_area"
        if any(k in txt for k in ["gruppo", "massiccio", "catena", "dorsale"]):
            return "mountain_group"
        if any(k in txt for k in ["monte", "montagna", "colle", "dosso", "poggio"]):
            return "mountain_area"
        if any(k in txt for k in ["cima", "vetta", "pizzo", "punta", "corno"]):
            return "summit_peak"
        if any(k in txt for k in ["lago", "valle", "val d", "val di"]):
            return ref_type or "locality"
        return ref_type or "generic_toponym"

    def _bbox_geometry(self, feature):
        bbox = feature.get("bbox") if isinstance(feature, dict) else None
        if bbox and len(bbox) == 4:
            return QgsGeometry.fromRect(QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3]))
        return None



    def _mountain_radius_m(self, feature, ref_type=None):
        """Raggio adattivo per toponimi montani.

        GeoLichen 2.8.5:
        usa un buffer medio per "Monte X", evitando di includere valli vicine.
        Se la quota del cartellino non è presente nel buffer, l'espansione
        viene gestita dal controller usando DEM + quota del record.
        """
        try:
            alt_ctx = feature.get("_geolichen_boundary_altitude") or {}
        except Exception:
            alt_ctx = {}

        canonical, radius = self.search_buffer_service.radius_for(ref_type or "mountain")
        return float(radius)


    def _mountain_bbox_or_buffer(self, feature, bbox_geom, ref_type="mountain_area"):
        """Usa bbox se sensata, altrimenti buffer adattivo."""
        radius = self._mountain_radius_m(feature, ref_type=ref_type)
        center_geom = self._point_from_feature(feature)

        if bbox_geom is None or bbox_geom.isEmpty():
            if center_geom:
                return self._metric_buffer_in_wgs84(center_geom, radius)
            return None

        w, h = self._bbox_size_m(bbox_geom)
        max_dim = max([x for x in [w, h] if x is not None], default=None)

        # Se bbox assente/piccola, usa buffer adattivo.
        if max_dim is None or max_dim < 1000:
            if center_geom:
                return self._metric_buffer_in_wgs84(center_geom, radius)
            return self._expand_rect_wgs84(bbox_geom, 300)

        # Se bbox è ragionevole, usala senza trasformarla in un mega-buffer.
        if max_dim <= radius * 2.2:
            return self._expand_rect_wgs84(bbox_geom, 300)

        # Se bbox è enorme, evita di forzare un calcolo gigantesco:
        # torna a un buffer adattivo centrato.
        if center_geom:
            return self._metric_buffer_in_wgs84(center_geom, radius)
        return self._expand_rect_wgs84(bbox_geom, 300)


    def _documented_extent(self, feature, ref_type, semantic_type, bbox_geom, interpretation=None):
        """Build the documentary locality geometry used by point-radius.

        Priority:
        1. a usable source bbox/geometry for an area-like feature;
        2. a type-specific *documentary estimate* when the source only gives a
           point-sized envelope for a locality explicitly classified as area;
        3. the geocoder centre for genuinely point-like features.

        The documentary estimate is intentionally distinct from the operational
        search buffer and is always marked as requiring verification.
        """
        center_geom = self._point_from_feature(feature)
        feature_type = getattr(interpretation, "feature_type", None) or semantic_type or ref_type
        expected_geometry = str(getattr(interpretation, "expected_geometry", "") or "").upper()
        strategy = self.strategy_resolver.strategy_for(feature_type, expected_geometry)

        # Unified rule: for intrinsically point-like features a geocoder point
        # is the complete documentary geometry.  It must never be routed to the
        # areal-missing fallback simply because the provider did not return a bbox.
        if strategy.point_is_valid and expected_geometry == "POINT" and center_geom is not None:
            return QgsGeometry(center_geom), "geocoder_feature_center", False

        area_like = (
            semantic_type in self.AREA_LIKE_TYPES
            or ref_type in self.AREA_LIKE_TYPES
            or feature.get("_geolichen_municipality_scope") in [
                "municipality_core", "municipality_extended"
            ]
        )

        # A municipality requires an administrative geometry. A lone point is
        # insufficient for a defensible municipality-wide uncertainty.
        if ref_type == "municipality":
            if bbox_geom is not None and not bbox_geom.isEmpty():
                return QgsGeometry(bbox_geom), "geocoder_admin_bbox", True
            return None, "municipality_geometry_missing", True

        if area_like:
            if bbox_geom is not None and not bbox_geom.isEmpty():
                w, h = self._bbox_size_m(bbox_geom)
                max_dim = max([v for v in (w, h) if v is not None], default=0.0)
                if max_dim >= self.MIN_DOCUMENTED_AREA_DIM_M:
                    return QgsGeometry(bbox_geom), "geocoder_area_bbox", False

            # The source describes an area but supplies only a point/tiny bbox.
            # Estimate the locality extent by semantic class; do not reuse the
            # search buffer because the two geometries serve different roles.
            radius = self.DOCUMENTED_FALLBACK_RADII.get(
                semantic_type,
                self.DOCUMENTED_FALLBACK_RADII.get(ref_type),
            )
            if radius and center_geom is not None:
                estimated = self._metric_buffer_in_wgs84(center_geom, radius)
                return (
                    estimated,
                    f"estimated_{semantic_type or ref_type}_extent_{float(radius):g}m",
                    True,
                )

            # An area with no usable source geometry and no documented fallback
            # is not calculable rather than being silently collapsed to a point.
            return None, "area_geometry_missing", True

        # Linear features may temporarily be represented by the geocoder
        # anchor when no line is available.  This is explicit and reviewable,
        # rather than being reported as a completely missing geometry.
        if expected_geometry == "LINE" and center_geom is not None:
            return QgsGeometry(center_geom), "geocoder_point_proxy", True

        # Genuinely point-like or generic named features remain points. Their
        # uncertainty comes from source/measurement/coordinate errors, not an
        # invented areal extent.
        if center_geom is not None:
            return QgsGeometry(center_geom), "geocoder_feature_center", False

        geom = self.feature_to_geometry(feature)
        return (QgsGeometry(geom), "geocoder_geometry", False) if geom else (None, "missing_geometry", True)

    def _search_extent(self, feature, ref_type, semantic_type, bbox_geom):
        """Build the operational geometry used to generate candidates.

        The geometry is selected by semantic type.  Source polygons/bboxes are
        preferred when defensible; point fallbacks use small, type-specific
        radii instead of a single generic 1.5 km buffer.
        """
        center_geom = self._point_from_feature(feature)
        raw_type = semantic_type or ref_type or "generic_toponym"
        canonical, strategy = self.search_buffer_service.strategy_for(raw_type)
        _, radius = self.search_buffer_service.radius_for(canonical)
        # Phase 15.4.0: the operative engine selects the provider-bbox margin.
        bbox_metric_plan = self.adaptive_search_geometry_engine.plan(
            canonical, decision="USE_GEOCODER_BBOX", source_kind="geocoder_bbox"
        )
        polygon_margin = float(bbox_metric_plan.polygon_margin_m or 0.0)

        # Località = comune: the complete administrative extent is the search
        # geometry. No semantic buffer is added.
        if canonical == "municipality" or ref_type == "municipality":
            if bbox_geom is not None and not bbox_geom.isEmpty():
                return QgsGeometry(bbox_geom), "municipality_full_extent"
            if center_geom is None:
                raise ValueError("Centro del comune non disponibile dal geocoder")
            return self._metric_buffer_in_wgs84(center_geom, radius), f"municipality_point_fallback_{radius:g}m"

        # A provider bbox is accepted only when its scale is compatible with
        # the semantic feature. Huge envelopes for peaks/passes/localities are
        # rejected in favour of the controlled semantic radius.
        if bbox_geom is not None and not bbox_geom.isEmpty():
            w, h = self._bbox_size_m(bbox_geom)
            max_dim = max([v for v in (w, h) if v is not None], default=0.0)
            min_dim = min([v for v in (w, h) if v is not None], default=0.0)
            max_allowed = float(strategy["max_radius_m"]) * 2.0

            bbox_is_usable = max_dim > 0.0 and max_dim <= max_allowed
            # Polygon-like semantic types may accept larger genuine source
            # extents, but still reject extreme geocoder envelopes.
            if canonical in {"mountain", "mountain_group", "valley", "forest", "lake", "meadow"}:
                bbox_is_usable = max_dim > 0.0 and max_dim <= max_allowed * 1.5

            if bbox_is_usable:
                expanded = self._expand_rect_wgs84(bbox_geom, polygon_margin)
                return expanded, f"semantic_{canonical}_bbox_plus_{polygon_margin:g}m"

        if center_geom is not None:
            # Phase 15.3.1: only the point-buffer branch becomes operative.
            # Explicit provider accuracy may enlarge a geocoder point fallback,
            # while semantic min/max bounds prevent uncontrolled expansion.
            source_accuracy_m = self._feature_accuracy_m(feature)
            point_metric_plan = self.adaptive_search_geometry_engine.plan(
                canonical,
                decision="USE_POINT_BUFFER",
                source_kind="geocoder_point",
                source_accuracy_m=source_accuracy_m,
            )
            selected_radius = float(point_metric_plan.point_radius_m or radius)
            geom = self._metric_buffer_in_wgs84(center_geom, selected_radius)
            shape = strategy.get("shape", "point_buffer")
            return geom, f"semantic_{canonical}_{shape}_{selected_radius:g}m"

        geom = self.feature_to_geometry(feature)
        return geom, f"semantic_{canonical}_geocoder_geometry_fallback"

    def _osm_search_extent(self, feature, ref_type, semantic_type, interpretation=None):
        """Try an OSM feature geometry before the semantic buffer fallback.

        Polygon features are used directly; line features become semantic
        corridors; point features become the usual type-specific point buffer.
        This changes only SearchGeometry, never DocumentedGeometry.
        """
        center_geom = self._point_from_feature(feature)
        if center_geom is None or center_geom.isEmpty():
            return None, None, None
        feature_type = getattr(interpretation, "feature_type", None) or semantic_type or ref_type
        canonical, strategy = self.search_buffer_service.strategy_for(feature_type)
        _, radius = self.search_buffer_service.radius_for(canonical)
        # Phase 15.1: the OSM lookup radius is now read from the same semantic
        # strategy registry as the operational buffer. Values are unchanged.
        _, query_radius = self.search_buffer_service.osm_query_radius_for(canonical)
        name = ""
        if isinstance(feature, dict):
            name = feature.get("text") or feature.get("place_name") or ""
        result = self.osm_search_geometry_service.resolve(
            name,
            canonical,
            center_geom,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            search_radius_m=query_radius,
        )
        if not result.success or result.geometry is None or result.geometry.isEmpty():
            return None, None, result

        geometry = QgsGeometry(result.geometry)
        geom_type = result.geometry_type
        if geom_type == "POLYGON":
            # Phase 15.3.3: OSM polygon expansion uses the same centralized
            # strategy as accepted provider bboxes.
            polygon_metric_plan = self.adaptive_search_geometry_engine.plan(
                canonical, decision="USE_OSM_POLYGON", source_kind="osm_polygon"
            )
            margin = float(polygon_metric_plan.polygon_margin_m or 0.0)
            if margin > 0:
                geometry = self._metric_buffer_in_wgs84(geometry, margin)
            strategy_name = f"{result.strategy}_plus_{margin:g}m" if margin else result.strategy
            return geometry, strategy_name, result
        if geom_type == "LINE":
            # Phase 15.3.2: every OSM line corridor reads its half-width from
            # the centralized semantic strategy registry. Values are kept
            # identical to the previous semantic radius in this refactoring.
            line_metric_plan = self.adaptive_search_geometry_engine.plan(
                canonical, decision="USE_LINE_CORRIDOR", source_kind="osm_line"
            )
            corridor_radius = float(line_metric_plan.line_corridor_radius_m or radius)
            geometry = self._metric_buffer_in_wgs84(geometry, corridor_radius)
            return geometry, f"{result.strategy}_corridor_{corridor_radius:g}m", result
        if geom_type == "POINT":
            # OSM point coordinates are precise, but precision is not locality
            # extent. Keep the semantic base radius in Phase 15.3.1.
            point_metric_plan = self.adaptive_search_geometry_engine.plan(
                canonical, decision="USE_POINT_BUFFER", source_kind="osm_point"
            )
            selected_radius = float(point_metric_plan.point_radius_m or radius)
            geometry = self._metric_buffer_in_wgs84(geometry, selected_radius)
            return geometry, f"{result.strategy}_buffer_{selected_radius:g}m", result
        return None, None, result

    def _source_kind(self, documented_source, documented, estimated=False):
        source = str(documented_source or "").lower()
        if "admin" in source:
            return "official_admin_polygon" if "official" in source else "geocoder_polygon"
        if "bbox" in source:
            return "geocoder_bbox"
        if source.startswith("estimated_") or estimated:
            return "semantic_estimate"
        if "point_proxy" in source:
            return "point_proxy"
        try:
            geom_type = int(documented.type()) if documented is not None else -1
        except Exception:
            geom_type = -1
        if geom_type == 2:
            return "geocoder_polygon"
        if geom_type == 1:
            return "osm_line"
        if geom_type == 0:
            return "geocoder_point"
        return "missing"

    @staticmethod
    def _feature_accuracy_m(feature):
        """Extract an explicit positional accuracy/radius from a provider hit.

        Providers use different fields.  Only positive metric-looking values
        are accepted; absent or non-numeric values remain ``None``.
        """
        if not isinstance(feature, dict):
            return None
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        candidates = [
            feature.get("accuracy_m"),
            feature.get("radius_m"),
            feature.get("accuracy"),
            props.get("accuracy_m"),
            props.get("radius_m"),
            props.get("accuracy"),
            props.get("radius"),
        ]
        for value in candidates:
            try:
                parsed = float(value)
            except Exception:
                continue
            if parsed > 0:
                return parsed
        return None

    def resolve_locality(self, feature, ref_type="generic_toponym", locality_context=None):
        """Create the authoritative ``ResolvedLocality`` for this geocoder hit."""
        if locality_context is not None:
            try:
                locality_context.update_boundary_metadata(ref_type)
            except Exception:
                pass

        geom = self.feature_to_geometry(feature)
        if geom is None or geom.isEmpty():
            raise ValueError("Geometria iniziale non disponibile dal geocoder")

        semantic_type = self._semantic_type_from_feature(feature, ref_type=ref_type)
        bbox_geom = self._bbox_geometry(feature)

        locality_text = ""
        municipality = ""
        if locality_context is not None:
            locality_text = locality_context.locality or locality_context.search_name or ""
            municipality = locality_context.municipality or ""
        if not locality_text:
            locality_text = feature.get("text") or feature.get("place_name") or ""

        interpretation = self.geometry_engine.parser.parse(locality_text, municipality)
        gre_result = self._resolve_document_geometry(semantic_type, {
            "feature": feature,
            "ref_type": ref_type,
            "semantic_type": semantic_type,
            "bbox_geometry": bbox_geom,
            "interpretation": interpretation,
            "locality_context": locality_context,
        })
        gre_result = GeometryResult.from_legacy(
            gre_result, semantic_type=semantic_type, resolver="GeometryResolutionEngine"
        )
        if gre_result.success:
            documented = gre_result.geometry
            documented_source = gre_result.source or "geometry_resolution_engine"
            requires_verification = bool(gre_result.requires_review)
        else:
            documented, documented_source, requires_verification = self._documented_extent(
                feature, ref_type, semantic_type, bbox_geom, interpretation=interpretation
            )
            fallback_resolver = (
                gre_result.resolver
                if gre_result.resolver and gre_result.resolver != "GeometryResolutionEngine"
                else "SemanticFallbackResolver"
            )
            geom_type = self._geometry_type_name(documented)
            gre_result = GeometryResult(
                geometry=documented,
                geometry_type=geom_type,
                semantic_type=str(semantic_type or ref_type or ""),
                resolver=fallback_resolver,
                decision="SEMANTIC_FALLBACK",
                source=str(documented_source or "semantic_estimate"),
                method=str(documented_source or "semantic_fallback"),
                confidence=float(getattr(interpretation, "confidence", 0.0) or 0.0),
                requires_review=bool(requires_verification),
                fallback_used=True,
                provenance=GeometryProvenance(
                    resolver_name=fallback_resolver,
                    source=str(documented_source or "semantic_estimate"),
                    geometry_type=geom_type,
                    confidence=float(getattr(interpretation, "confidence", 0.0) or 0.0),
                    fallback_used=True,
                ),
                metadata={
                    "primary_gre_decision": getattr(gre_result, "decision", "FAILED"),
                    "primary_gre_method": getattr(gre_result, "method", ""),
                    "legacy_fallback": True,
                },
                stage="documented",
            )
        # Workflow point 3 has one authoritative result.  OSM is tried first;
        # the existing semantic geometry is the unchanged deterministic fallback.
        search_resolution = self.search_geometry_resolution_service.resolve(
            osm_builder=lambda: self._osm_search_extent(
                feature, ref_type, semantic_type, interpretation=interpretation
            ),
            semantic_builder=lambda: self._search_extent(
                feature, ref_type, semantic_type, bbox_geom
            ),
        )
        search = search_resolution.geometry
        search_strategy = search_resolution.strategy
        osm_search_result = search_resolution.osm_result

        # Phase 15.2: produce a diagnostic-only AdaptiveBufferPlan.  It records
        # the values already used by the pipeline and does not modify geometry.
        plan_feature_type = getattr(interpretation, "feature_type", None) or semantic_type or ref_type
        try:
            plan_geometry_type = str(getattr(osm_search_result, "geometry_type", "") or "").upper()
        except Exception:
            plan_geometry_type = ""
        if not plan_geometry_type:
            try:
                qgis_type = int(search.type()) if search is not None else -1
            except Exception:
                qgis_type = -1
            plan_geometry_type = {0: "POINT", 1: "LINE", 2: "POLYGON"}.get(qgis_type, "UNKNOWN")
        altitude_ctx = feature.get("_geolichen_boundary_altitude") if isinstance(feature, dict) else None
        record_altitude_available = bool(
            isinstance(altitude_ctx, dict) and altitude_ctx.get("has_altitude")
        )
        # Phase 15.2b: classify the already-selected geometry strategy in one
        # diagnostic decision engine.  This does not create or replace geometry.
        source_bbox_available = bool(
            isinstance(feature, dict) and feature.get("bbox")
        )
        canonical_plan_type = self.search_buffer_service.canonical_type(plan_feature_type)
        geometry_decision = self.adaptive_buffer_decision_service.decide(
            canonical_type=canonical_plan_type,
            geometry_type=plan_geometry_type,
            selected_strategy=search_strategy,
            source=search_resolution.source,
            used_osm=search_resolution.used_osm,
            used_fallback=search_resolution.used_fallback,
            source_bbox_available=source_bbox_available,
        )
        source_kind_for_plan = "unknown"
        source_accuracy_for_plan = None
        if geometry_decision.decision == self.adaptive_buffer_decision_service.USE_POINT_BUFFER:
            source_kind_for_plan = "osm_point" if search_resolution.used_osm else "geocoder_point"
            source_accuracy_for_plan = None if search_resolution.used_osm else self._feature_accuracy_m(feature)
        elif geometry_decision.decision == self.adaptive_buffer_decision_service.USE_LINE_CORRIDOR:
            source_kind_for_plan = "osm_line"
        elif geometry_decision.decision == self.adaptive_buffer_decision_service.USE_OSM_POLYGON:
            source_kind_for_plan = "osm_polygon"
        elif geometry_decision.decision == self.adaptive_buffer_decision_service.USE_GEOCODER_BBOX:
            source_kind_for_plan = "geocoder_bbox"
        elif geometry_decision.decision == self.adaptive_buffer_decision_service.USE_ADMINISTRATIVE_EXTENT:
            source_kind_for_plan = "administrative_extent"

        adaptive_geometry_result = self.adaptive_search_geometry_engine.plan(
            plan_feature_type,
            decision=geometry_decision.decision,
            source_kind=source_kind_for_plan,
            source_accuracy_m=source_accuracy_for_plan,
        )
        selected_radius_m = adaptive_geometry_result.point_radius_m
        adaptive_reasons = [f"strategy={search_strategy}"]
        adaptive_reasons.extend(adaptive_geometry_result.reasons)
        adaptive_behavior_changed = adaptive_geometry_result.behavior_changed
        adaptive_plan = self.search_buffer_service.build_adaptive_plan(
            plan_feature_type,
            geometry_source=search_resolution.source,
            geometry_type=plan_geometry_type,
            used_osm=search_resolution.used_osm,
            fallback_used=search_resolution.used_fallback,
            record_altitude_available=record_altitude_available,
            selected_radius_m=selected_radius_m,
            selected_line_corridor_m=adaptive_geometry_result.line_corridor_radius_m,
            selected_polygon_margin_m=adaptive_geometry_result.polygon_margin_m,
            extra_reasons=tuple(adaptive_reasons),
            decision=geometry_decision,
            behavior_changed=adaptive_behavior_changed,
        )
        search_metadata = dict(search_resolution.metadata or {})
        search_metadata["search_geometry_decision"] = geometry_decision.to_dict()
        search_metadata["adaptive_buffer_plan"] = adaptive_plan.to_dict()
        search_metadata["adaptive_search_geometry_result"] = adaptive_geometry_result.to_dict()
        administrative_geometry_diagnostics = self._administrative_geometry_diagnostics(
            feature=feature,
            ref_type=ref_type,
            semantic_type=semantic_type,
            interpretation=interpretation,
            bbox_geom=bbox_geom,
            documented=documented,
            documented_source=documented_source,
            search_resolution=search_resolution,
            search=search,
            search_strategy=search_strategy,
            osm_search_result=osm_search_result,
            locality_text=locality_text,
            municipality=municipality,
        )
        search_metadata["administrative_geometry_diagnostics"] = administrative_geometry_diagnostics

        # 15.4.5 Sprint 1: bind documentary and operational geometry into one
        # validated core context. This is additive and intentionally does not
        # change the geometry selected by the established search pipeline.
        search_result = GeometryResult(
            geometry=search,
            geometry_type=self._geometry_type_name(search),
            semantic_type=str(semantic_type or ref_type or ""),
            resolver="SearchGeometryResolutionService",
            decision="SEARCH_GEOMETRY_SELECTED" if search is not None else "SEARCH_GEOMETRY_MISSING",
            source=str(search_resolution.source or ""),
            method=str(search_strategy or ""),
            confidence=float(getattr(gre_result, "confidence", 0.0) or 0.0),
            requires_review=bool(search_resolution.used_fallback),
            fallback_used=bool(search_resolution.used_fallback),
            metadata={
                "used_osm": bool(search_resolution.used_osm),
                "used_fallback": bool(search_resolution.used_fallback),
                "resolution_metadata": dict(search_metadata),
            },
            stage="search",
        )
        geometry_core_context = GeoreferencingGeometryContext(
            semantic_type=str(semantic_type or ref_type or ""),
            documented=gre_result,
            search=search_result,
            metadata={
                "documented_source": str(documented_source or ""),
                "search_strategy": str(search_strategy or ""),
                "same_geometry_object": bool(documented is search),
                "resolver_family": (gre_result.metadata or {}).get("resolver_family", ""),
                "semantic_resolver_version": "SLGE-2.0",
                "documented_geometry_type": self._geometry_type_name(documented),
                "search_geometry_type": self._geometry_type_name(search),
                "geometry_alignment": (
                    "same_geometry" if documented is search else
                    "documented_and_search_separated_by_design"
                ),
            },
        )
        search_metadata["geometry_core_context"] = geometry_core_context.to_dict()

        estimated = str(documented_source or "").startswith("estimated_")
        source_kind = self._source_kind(documented_source, documented, estimated)
        resolved = self.geometry_engine.resolve(
            locality_text,
            municipality,
            source_geometry=documented,
            source_kind=source_kind,
            source_identifier=str(feature.get("id") or feature.get("place_id") or "") or None,
            search_geometry=search,
            search_strategy=search_strategy,
            search_source=search_resolution.source,
            search_metadata=search_metadata,
            geometry_method=documented_source,
            estimated=estimated,
            requires_review=bool(requires_verification),
            interpretation=interpretation,
            metadata={
                "semantic_type_legacy": semantic_type,
                "reference_type": ref_type,
                "provider": feature.get("provider"),
                "place_name": feature.get("place_name"),
                # Preserve the original geocoder envelope even when the
                # documentary representation is correctly POINT.  The bbox is
                # source-accuracy evidence for point-radius, not a replacement
                # for the point geometry itself.
                "source_bbox": list(feature.get("bbox") or []) if isinstance(feature, dict) else [],
                "source_center": list(feature.get("center") or []) if isinstance(feature, dict) else [],
                "source_relevance": feature.get("relevance") if isinstance(feature, dict) else None,
                "source_accuracy_m": self._feature_accuracy_m(feature),
                "source_label": self.strategy_resolver.source_label(source_kind),
                "method_label": self.strategy_resolver.method_label(documented_source),
                "osm_search_geometry_used": bool(search_resolution.used_osm),
                "osm_search_geometry_type": getattr(osm_search_result, "geometry_type", "") if osm_search_result else "",
                "osm_search_geometry_id": getattr(osm_search_result, "osm_id", 0) if osm_search_result else 0,
                "osm_search_geometry_name": getattr(osm_search_result, "name", "") if osm_search_result else "",
                "osm_search_geometry_strategy": search_strategy if str(search_strategy).startswith("osm_") else "",
                "osm_search_geometry_from_cache": bool(getattr(osm_search_result, "from_cache", False)) if osm_search_result else False,
                "administrative_geometry_diagnostics": administrative_geometry_diagnostics,
                "gre_result": gre_result.to_dict(),
                "gre_resolver": gre_result.resolver,
                "gre_resolver_family": (gre_result.metadata or {}).get("resolver_family", ""),
                "gre_decision": gre_result.decision,
                "gre_source": gre_result.source,
                "gre_method": gre_result.method,
                "gre_geometry_type": gre_result.geometry_type,
                "gre_confidence": gre_result.confidence,
                "gre_fallback_used": gre_result.fallback_used,
                "geometry_core_context": geometry_core_context.to_dict(),
                "search_geometry_result": search_result.to_dict(include_geometry=False),
            },
        )
        resolved.provenance.update({
            "version": "SLGE-2.0",
            "boundary_service": "InitialBoundaryService/SLGE",
            "documented_extent_source": documented_source,
            "search_extent_strategy": search_strategy,
            "osm_search_geometry_used": bool(search_resolution.used_osm),
            "osm_search_geometry_id": getattr(osm_search_result, "osm_id", 0) if osm_search_result else 0,
            "osm_search_geometry_name": getattr(osm_search_result, "name", "") if osm_search_result else "",
            "osm_data_source": "© OpenStreetMap contributors" if search_resolution.used_osm else "",
            "search_geometry_source": search_resolution.source,
            "search_geometry_fallback_used": bool(search_resolution.used_fallback),
            "administrative_geometry_diagnostics": administrative_geometry_diagnostics,
            "geometry_resolution_engine": gre_result.to_dict(),
            "gre_resolver": gre_result.resolver,
            "gre_resolver_family": (gre_result.metadata or {}).get("resolver_family", ""),
            "gre_decision": gre_result.decision,
            "gre_source": gre_result.source,
            "gre_method": gre_result.method,
            "gre_geometry_type": gre_result.geometry_type,
            "gre_confidence": gre_result.confidence,
            "gre_fallback_used": gre_result.fallback_used,
            "geometry_core_context": geometry_core_context.to_dict(),
            "search_geometry_result": search_result.to_dict(include_geometry=False),
        })

        if locality_context is not None:
            locality_context.set_resolved_locality(resolved)

        return resolved

    def build_extents(self, feature, ref_type="generic_toponym", locality_context=None):
        """Compatibility API exposing geometries from one resolved object."""
        resolved = self.resolve_locality(feature, ref_type, locality_context)
        documented = resolved.documented_geometry.geometry
        search = resolved.search_geometry.geometry
        return {
            "resolved_locality": resolved,
            "documented_extent": documented,
            "search_extent": search,
            "documented_extent_source": resolved.documented_geometry.method,
            "search_extent_strategy": resolved.search_geometry.strategy,
            "documented_extent_requires_verification": resolved.documented_geometry.requires_review,
            "semantic_type": resolved.interpretation.feature_type,
        }

    def build_boundary(self, feature, ref_type="generic_toponym", locality_context=None):
        """Compatibility wrapper returning only the operational extent."""
        return self.build_extents(
            feature, ref_type=ref_type, locality_context=locality_context
        )["search_extent"]


    def _resolve_document_geometry(self, semantic_type, context):
        """Resolve authoritative geometry through the Geometry Resolution Engine."""
        try:
            result = self.geometry_resolution_engine.resolve(semantic_type, context)
            return result
        except Exception:
            return None
