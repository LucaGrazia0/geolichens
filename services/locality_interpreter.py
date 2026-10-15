import re
import unicodedata

from ..models.locality_context import LocalityContext
from .locality_offset_parser import LocalityOffsetParser


class LocalityInterpreter:
    """Crea, classifica e sincronizza il contesto geografico condiviso.

    Fase 6: assegna un tipo di località di alto livello senza modificare le
    regole operative di geocoding, boundary, GSS o ranking.
    """

    def __init__(self):
        self.offset_parser = LocalityOffsetParser()

    BROAD_TYPES = {
        "municipality",
        "municipality_only",
        "named_feature",
        "near_feature",
        "between_features",
        "linear_feature",
        "coordinates",
        "unknown",
    }

    LINEAR_REFERENCE_TYPES = {"trail", "hydro"}
    AREA_REFERENCE_TYPES = {
        "municipality", "forest_area", "valley", "mountain_area",
        "mountain_group", "meadow",
    }
    POINT_REFERENCE_TYPES = {"summit", "summit_peak", "pass", "refuge_malga"}

    @staticmethod
    def _clean(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize(value) -> str:
        text = str(value or "").strip().replace("’", "'").replace("`", "'")
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", text.casefold()).strip()

    def build_context(self, municipality=None, locality=None) -> LocalityContext:
        municipality_text = self._clean(municipality)
        locality_text = self._clean(locality)
        same_as_municipality = (
            bool(municipality_text)
            and self._normalize(municipality_text) == self._normalize(locality_text)
        )
        search_name = locality_text or municipality_text
        context = LocalityContext(
            municipality=municipality_text,
            locality=locality_text,
            normalized_locality=search_name,
            search_name=search_name,
            same_as_municipality=same_as_municipality,
            search_strategy=(
                "municipality_only" if (same_as_municipality or not locality_text)
                else "municipality_guided"
            ),
        )
        context.offset_spec = self.offset_parser.parse(locality_text)
        return self.classify(context)

    @staticmethod
    def _looks_like_coordinates(text: str) -> bool:
        if not text:
            return False
        decimal_pair = re.search(
            r"(?<!\d)[+-]?(?:[0-8]?\d(?:\.\d+)?|90(?:\.0+)?)\s*[,; ]\s*"
            r"[+-]?(?:1[0-7]\d(?:\.\d+)?|\d?\d(?:\.\d+)?|180(?:\.0+)?)(?!\d)",
            text,
        )
        dms = re.search(
            r"\d{1,3}\s*[°º]\s*\d{1,2}\s*['′]\s*(?:\d{1,2}(?:\.\d+)?)?\s*[\"″]?\s*[NSEW]",
            text,
            re.IGNORECASE,
        )
        return bool(decimal_pair or dms)

    @staticmethod
    def _feature_geometry_type(feature) -> str:
        if not isinstance(feature, dict):
            return "unknown"
        geometry = feature.get("geometry") or {}
        geom_type = str(geometry.get("type") or "").casefold()
        if "point" in geom_type:
            return "point"
        if "line" in geom_type:
            return "line"
        if "polygon" in geom_type:
            return "area"
        bbox = feature.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            return "area"
        center = feature.get("center")
        if isinstance(center, (list, tuple)) and len(center) == 2:
            return "point"
        return "unknown"

    def _references(self, parse_result):
        try:
            return list(parse_result.best_references())
        except Exception:
            return []

    def classify(
        self,
        context,
        parse_result=None,
        geocoding_result=None,
        ref_type=None,
        manual=False,
    ):
        """Classifica il record usando segnali testuali, parser e geocoder.

        L'ordine è intenzionalmente conservativo. La classificazione viene
        salvata nel contesto ma non viene usata per cambiare l'algoritmo
        operativo nella Fase 6.
        """
        if context is None:
            return None

        if parse_result is not None:
            context.apply_parse_result(parse_result)

        text = self._normalize(context.locality or context.search_name)
        municipality = self._normalize(context.municipality)
        refs = self._references(parse_result)
        ref_types = [getattr(r, "ref_type", "") or "" for r in refs]
        relations = [getattr(r, "relation", "") or "" for r in refs]
        signals = []

        matched_ref = ref_type or getattr(geocoding_result, "matched_source", None)
        if matched_ref:
            context.primary_reference_type = str(matched_ref)
            signals.append(f"ref_type:{matched_ref}")

        feature = getattr(geocoding_result, "feature", None)
        feature_geom = self._feature_geometry_type(feature)
        if feature_geom != "unknown":
            signals.append(f"geocoder_geometry:{feature_geom}")

        if manual:
            context.apply_classification(
                "manual_search_area", "area",
                "Area operativa definita dall’operatore mediante punto centrale e buffer manuale; "
                "il punto non è una coordinata dichiarata del reperto.", 1.0,
                signals + ["manual_point", "manual_search_buffer"],
                search_strategy="manual_point_buffer",
                buffer_strategy="manual_radius",
            )
            return context

        if self._looks_like_coordinates(text):
            context.apply_classification(
                "coordinates", "point",
                "La località contiene una coppia di coordinate esplicite.", 0.99,
                signals + ["coordinate_pattern"],
                search_strategy="coordinates",
                buffer_strategy="coordinate_precision",
            )
            return context

        offset_kind = str((getattr(context, "offset_spec", None) or {}).get("kind") or "")
        if offset_kind:
            offset_labels = {
                "distance_at_heading": ("offset_at_heading", "offset_area", "Distanza a una direzione"),
                "orthogonal_offsets": ("offset_orthogonal", "offset_area", "Distanze ortogonali"),
                "distance_only": ("offset_distance_only", "offset_area", "Distanza senza direzione"),
                "along_path": ("offset_along_path", "line", "Distanza lungo un percorso"),
                "two_distinct_paths": ("offset_two_paths", "area", "Distanze da due percorsi distinti"),
            }
            loc_type, geom_type, label = offset_labels.get(
                offset_kind, ("near_feature", "offset_area", "Offset geografico")
            )
            context.apply_classification(
                loc_type, geom_type,
                f"La descrizione contiene un offset geografico interpretabile: {label}.",
                0.95, signals + [f"offset:{offset_kind}"],
                search_strategy="gbif_offset_geometry",
                buffer_strategy="offset_derived_extent",
            )
            return context

        has_between = (
            "between" in relations
            or bool(re.search(r"\b(?:tra|fra)\b.+\be\b", text))
        )
        if has_between:
            context.apply_classification(
                "between_features", "corridor",
                "La descrizione colloca il reperto tra due riferimenti geografici.", 0.94,
                signals + ["between_relation"],
                search_strategy="between_references",
                buffer_strategy="between_extent",
            )
            return context

        has_near = (
            any(rel in {"near", "above", "below"} for rel in relations)
            or bool(re.search(r"\b(?:nei pressi di|vicino a|presso|in prossimita di|sopra|sotto)\b", text))
        )
        if has_near:
            context.apply_classification(
                "near_feature", "offset_area",
                "La descrizione esprime una relazione di prossimità o posizione relativa.", 0.91,
                signals + ["near_relation"],
                search_strategy="reference_with_offset",
                buffer_strategy="proximity_extent",
            )
            return context

        linear_ref = next((r for r in ref_types if r in self.LINEAR_REFERENCE_TYPES), None)
        linear_text = bool(re.search(r"\b(?:sentiero|mulattiera|traccia|strada|canale|torrente|rio|fiume)\b", text))
        if linear_ref or linear_text:
            context.apply_classification(
                "linear_feature", "line",
                "La località identifica o segue un elemento geografico lineare.", 0.88,
                signals + ([f"linear_ref:{linear_ref}"] if linear_ref else ["linear_keyword"]),
                search_strategy="linear_feature",
                buffer_strategy="line_corridor",
            )
            return context

        no_locality = not self._normalize(context.locality)
        if context.same_as_municipality or (no_locality and municipality):
            locality_type = "municipality_only" if no_locality else "municipality"
            reason = (
                "È disponibile soltanto il Comune."
                if no_locality else
                "Il valore di Località coincide con il Comune."
            )
            context.apply_classification(
                locality_type, "area", reason, 0.99,
                signals + ["municipality_scope"],
                search_strategy="municipality_only",
                buffer_strategy="municipality_extent",
            )
            return context

        effective_ref = matched_ref or (ref_types[0] if ref_types else "")
        if effective_ref == "municipality":
            context.apply_classification(
                "municipality", "area",
                "Il riferimento principale è stato riconosciuto come Comune.", 0.96,
                signals + ["municipality_reference"],
                search_strategy="municipality",
                buffer_strategy="municipality_extent",
            )
            return context

        if text or effective_ref:
            if effective_ref in self.AREA_REFERENCE_TYPES:
                geometry_type = "area"
            elif effective_ref in self.POINT_REFERENCE_TYPES:
                geometry_type = "point"
            elif feature_geom != "unknown":
                geometry_type = feature_geom
            else:
                geometry_type = "feature"
            confidence = 0.90 if effective_ref and effective_ref != "generic_toponym" else 0.68
            reason = (
                f"Località associata a un riferimento geografico denominato ({effective_ref})."
                if effective_ref else
                "La descrizione contiene un toponimo, ma il tipo specifico non è noto."
            )
            context.apply_classification(
                "named_feature", geometry_type, reason, confidence,
                signals + ([f"named_ref:{effective_ref}"] if effective_ref else ["named_text"]),
                search_strategy="named_feature",
                buffer_strategy="feature_extent",
            )
            return context

        context.apply_classification(
            "unknown", "unknown",
            "Informazioni insufficienti per classificare la località.", 0.0,
            signals + ["insufficient_information"],
            search_strategy="default",
            buffer_strategy="default",
        )
        return context

    def update_extents(
        self,
        context,
        original_locality_extent=None,
        search_extent=None,
        ecological_extent=None,
    ):
        """Sincronizza geometrie senza duplicare logica."""
        if context is None:
            return None
        context.update_extents(
            original_locality_extent=original_locality_extent,
            search_extent=search_extent,
            ecological_extent=ecological_extent,
        )
        return context
