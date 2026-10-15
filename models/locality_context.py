from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LocalityContext:
    """Contesto geografico condiviso tra controller e servizi.

    Dalla Fase 6 conserva anche la classificazione geografica della località.
    La classificazione è descrittiva: non modifica geocoding, buffer, GSS o
    selezione del punto ecologico.
    """

    municipality: str = ""
    locality: str = ""
    normalized_locality: str = ""
    search_name: str = ""
    same_as_municipality: bool = False

    # Classificazione GBIF/GeoLichen di alto livello.
    locality_type: str = "unknown"
    geometry_type: str = "unknown"
    classification_reason: str = ""
    classification_confidence: float = 0.0
    classification_signals: List[str] = field(default_factory=list)

    # Riferimento semantico più specifico prodotto dal parser/geocoder.
    primary_reference_type: str = ""
    primary_reference_name: str = ""
    primary_relation: str = ""

    buffer_strategy: str = "default"
    search_strategy: str = "default"
    preferred_dem: Optional[str] = None

    original_locality_extent: Any = None
    search_extent: Any = None
    ecological_extent: Any = None
    resolved_locality: Any = None

    # Provenance of the separated documentary and operational geometries.
    documented_extent_source: str = ""
    search_extent_strategy: str = ""
    documented_extent_requires_verification: bool = False

    # FASE 7: centro geografico documentale GBIF, separato dal punto GSS.
    geocoded_center: Any = None
    gbif_corrected_center: Any = None
    gbif_corrected_center_method: str = ""
    gbif_corrected_center_source: str = ""
    gbif_corrected_center_reason: str = ""
    remarks: str = ""

    # FASE 10: descrizione strutturata degli offset e geometria finale GBIF.
    offset_spec: Dict[str, Any] = field(default_factory=dict)
    offset_path_a: Any = None
    offset_path_b: Any = None
    final_locality_extent: Any = None
    locality_geometry_method: str = ""
    locality_geometry_reason: str = ""
    locality_geometry_applied: bool = False
    locality_geometry_requires_verification: bool = False

    def parsing_text(self) -> str:
        """Restituisce il testo da inviare al parser secondo la priorità storica."""
        return self.locality or self.search_name or ""

    def apply_parse_result(self, result) -> None:
        """Registra i metadati descrittivi prodotti dal parser.

        La classificazione di alto livello viene assegnata dal
        ``LocalityInterpreter`` e non viene sovrascritta con i tipi interni del
        parser (es. ``mountain_area`` o ``summit_peak``).
        """
        if result is None:
            return
        cleaned = getattr(result, "cleaned_text", None)
        if cleaned:
            self.normalized_locality = cleaned
        try:
            references = result.best_references()
        except Exception:
            references = []
        if references:
            ref = references[0]
            self.primary_reference_type = getattr(ref, "ref_type", "") or ""
            self.primary_reference_name = getattr(ref, "normalized_name", "") or ""
            self.primary_relation = getattr(ref, "relation", "") or ""

    def apply_classification(
        self,
        locality_type: str,
        geometry_type: str,
        reason: str,
        confidence: float,
        signals=None,
        search_strategy: Optional[str] = None,
        buffer_strategy: Optional[str] = None,
    ) -> None:
        """Aggiorna in modo atomico la classificazione della località."""
        self.locality_type = locality_type or "unknown"
        self.geometry_type = geometry_type or "unknown"
        self.classification_reason = reason or ""
        try:
            self.classification_confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            self.classification_confidence = 0.0
        self.classification_signals = list(signals or [])
        if search_strategy:
            self.search_strategy = search_strategy
        if buffer_strategy:
            self.buffer_strategy = buffer_strategy

    def update_boundary_metadata(self, ref_type: Optional[str]) -> None:
        """Registra il tipo specifico usato dal servizio boundary.

        Non sovrascrive ``geometry_type`` della Fase 6: il ref_type specifico
        viene conservato in ``primary_reference_type``.
        """
        if ref_type:
            self.primary_reference_type = ref_type

    def update_extents(
        self,
        original_locality_extent=None,
        search_extent=None,
        ecological_extent=None,
    ) -> None:
        """Aggiorna solo le geometrie esplicitamente fornite."""
        if original_locality_extent is not None:
            self.original_locality_extent = original_locality_extent
        if search_extent is not None:
            self.search_extent = search_extent
        if ecological_extent is not None:
            self.ecological_extent = ecological_extent


    def set_resolved_locality(self, resolved) -> None:
        """Attach the SLGE aggregate and synchronize compatibility fields.

        Documentary geometry is copied once from the immutable container.
        Operational geometry remains mutable through ``SearchGeometry``.
        """
        self.resolved_locality = resolved
        if resolved is None:
            return
        documented = getattr(resolved, "documented_geometry", None)
        search = getattr(resolved, "search_geometry", None)
        if documented is not None:
            self.original_locality_extent = getattr(documented, "geometry", None)
            self.documented_extent_source = getattr(documented, "method", "") or getattr(documented, "source", "")
            self.documented_extent_requires_verification = bool(getattr(documented, "requires_review", False))
        if search is not None:
            self.search_extent = getattr(search, "geometry", None)
            self.search_extent_strategy = getattr(search, "strategy", "")
            self.buffer_strategy = self.search_extent_strategy or self.buffer_strategy

    def replace_search_extent(self, geometry, reason="") -> None:
        """Update only the operational geometry, never the documented one."""
        self.search_extent = geometry
        resolved = self.resolved_locality
        if resolved is not None and getattr(resolved, "search_geometry", None) is not None:
            resolved.search_geometry.replace_geometry(geometry, reason=reason or None)

    def set_geocoded_center(self, point) -> None:
        """Conserva il centro restituito dal geocoder senza usarlo nel GSS."""
        self.geocoded_center = point

    def set_gbif_corrected_center(self, point, method="", source="", reason="") -> None:
        """Registra il centro corretto GBIF, indipendente dal punto ecologico."""
        self.gbif_corrected_center = point
        self.gbif_corrected_center_method = method or ""
        self.gbif_corrected_center_source = source or ""
        self.gbif_corrected_center_reason = reason or ""

    def classification_dict(self) -> Dict[str, Any]:
        """Ritorna una rappresentazione serializzabile della classificazione."""
        return {
            "locality_type": self.locality_type,
            "geometry_type": self.geometry_type,
            "classification_reason": self.classification_reason,
            "classification_confidence": self.classification_confidence,
            "classification_signals": list(self.classification_signals),
            "primary_reference_type": self.primary_reference_type,
            "primary_reference_name": self.primary_reference_name,
            "primary_relation": self.primary_relation,
            "same_as_municipality": self.same_as_municipality,
            "search_strategy": self.search_strategy,
            "buffer_strategy": self.buffer_strategy,
            "documented_extent_source": self.documented_extent_source,
            "search_extent_strategy": self.search_extent_strategy,
            "documented_extent_requires_verification": self.documented_extent_requires_verification,
            "gbif_corrected_center_method": self.gbif_corrected_center_method,
            "gbif_corrected_center_source": self.gbif_corrected_center_source,
            "gbif_corrected_center_reason": self.gbif_corrected_center_reason,
            "offset_spec": dict(self.offset_spec or {}),
            "locality_geometry_method": self.locality_geometry_method,
            "locality_geometry_reason": self.locality_geometry_reason,
            "locality_geometry_applied": self.locality_geometry_applied,
            "locality_geometry_requires_verification": self.locality_geometry_requires_verification,
            "slge_resolved": bool(self.resolved_locality is not None),
            "slge_geometry_confidence": (getattr(self.resolved_locality, "geometry_confidence", None) if self.resolved_locality is not None else None),
        }
