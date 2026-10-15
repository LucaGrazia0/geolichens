from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayerType,
    QgsProject,
)
from .lithology_classifier_service import LithologyClassifierService


class EnvironmentOverlayService:
    """Applica l'overlay ambientale al boundary iniziale.

    - preferisce il campo GRUPPO_LITO se presente
    - auto-detect del campo geologico migliore
    - riclassificazione litologica in: calcareo/siliceo/misto
    - match morbido: se nessuna feature geologica, warning ma non blocco
    - trasformazioni CRS corrette tra boundary WGS84 e layer target
    """

    GEOLOGY_FIELD_HINTS = [
        'GRUPPO_LITO', 'LITOLOGIA', 'DESCRIZIONE', 'DESCRIZION', 'UNITA', 'FORMAZIONE', 'NOME', 'SIGLA', 'DESCR'
    ]

    def __init__(self):
        self.lithology_classifier = LithologyClassifierService()


    def _record_substrate_text(self, constraints):
        """Restituisce solo il substrato esplicito del record/cartellino."""
        constraints = constraints or {}
        values = [
            constraints.get("record_substrate"),
            constraints.get("substrate_raw"),
            constraints.get("substrate"),
        ]
        return " ".join(str(v or "").strip().lower() for v in values)

    def _is_explicit_rock_substrate_constraint(self, constraints):
        """True solo se il cartellino indica esplicitamente roccia/sassicolo."""
        if str((constraints or {}).get("substrate_group") or "").lower() == "rock":
            return True
        txt = self._record_substrate_text(constraints)
        rock_terms = [
            "roccia",
            "sassicol",
            "saxicol",
            "rupicol",
            "rupestre",
        ]
        return any(term in txt for term in rock_terms)

    def _is_soil_substrate_constraint(self, constraints):
        if str((constraints or {}).get("substrate_group") or "").lower() in ("soil", "moss"):
            return True
        txt = self._record_substrate_text(constraints)
        soil_terms = [
            "suolo",
            "soil",
            "terra",
            "terric",
            "humus",
            "torba",
            "sabbia",
            "argilla",
            "ghiaia",
            "detrito",
            "morena",
        ]
        return any(term in txt for term in soil_terms)


    def _is_epiphyte_substrate_constraint(self, constraints):
        constraints = constraints or {}
        if str(constraints.get("substrate_group") or "").lower() in ("epiphyte", "lignicolous"):
            return True
        values = [constraints.get("substrate"), constraints.get("substrate_raw"), constraints.get("tree_raw"), constraints.get("tree_type")]
        txt = " ".join(str(v or "").lower() for v in values)
        ep_terms = ["scorza", "corteccia", "bark", "epif", "forofita", "tronco", "ramo", "legno", "wood"]
        return any(t in txt for t in ep_terms)


    def apply(self, boundary_geom, geology_layer=None, geology_field=None,
              soil_layer=None, soil_field=None,
              trees_layer=None, trees_field=None,
              constraints=None):
        if boundary_geom is None or boundary_geom.isEmpty():
            raise ValueError('Boundary iniziale assente o vuoto')

        constraints = constraints or {}

        # GeoLichen buffer fix:
        # la geologia può restringere il boundary solo se il cartellino
        # dichiara esplicitamente un substrato sassicolo/roccioso.
        geology_clip_allowed = self._is_explicit_rock_substrate_constraint(
            constraints
        )

        result_geom = QgsGeometry(boundary_geom)
        details = []
        warnings = []
        blocking_reasons = []
        score = 100.0

        rock_type = self._normalize_constraint(constraints.get('rock_type'))
        substrate = self._normalize_constraint(constraints.get('substrate'))
        tree_type = self._normalize_constraint(constraints.get('tree_type'))
        layer_decision = constraints.get('layer_decision') or {}
        use_geology = layer_decision.get('use_geology', True)
        use_soil = layer_decision.get('use_soil', True)
        use_trees = layer_decision.get('use_trees', True)
        soil_ph_preference = self._normalize_constraint(layer_decision.get('soil_ph_preference') or constraints.get('soil_ph_preference'))
        if layer_decision:
            details.append('Decisione ecologica: ' + str(layer_decision.get('explain') or layer_decision.get('primary_layer') or '-'))
        fallback_substrata = [self._normalize_constraint(x) for x in constraints.get('fallback_substrata', []) if x]
        habitat_classes = [self._normalize_constraint(x) for x in constraints.get('habitat_classes', constraints.get('fallback_habitat', [])) if x]
        resolved_group = str(constraints.get("substrate_group") or "").strip().lower()
        group_map = {"soil": "soil", "moss": "soil", "rock": "rock", "epiphyte": "tree", "lignicolous": "tree"}
        substrate_group = group_map.get(resolved_group) or self._substrate_group(
            substrate, fallback_substrata=fallback_substrata, habitat_classes=habitat_classes
        )
        if habitat_classes:
            details.append('Classi habitat ITALIC: ' + ', '.join(habitat_classes))
            if 'alpino' in habitat_classes:
                score -= 2
        if substrate_group:
            details.append(f'Gruppo substrato: {substrate_group}')

        resolved_geology_field = geology_field
        if geology_layer:
            resolved_geology_field = self._resolve_geology_field(geology_layer, geology_field)
            if resolved_geology_field:
                details.append(f'Campo geologia: {resolved_geology_field}')

        if (
            geology_layer
            and resolved_geology_field
            and rock_type
            and use_geology
            and geology_clip_allowed
        ):
            matched, matched_count = self._collect_matching_geometry(
                geology_layer, resolved_geology_field, rock_type, result_geom,
                use_lithology_classifier=(resolved_geology_field.upper() != 'GRUPPO_LITO')
            )
            if matched and not matched.isEmpty():
                inter = result_geom.intersection(matched)
                if inter and not inter.isEmpty():
                    result_geom = inter
                    details.append(f'Boundary ristretto da geologia/litologia: {rock_type} ({matched_count} feature)')
                    score -= 5
                else:
                    warnings.append(f"Le feature geologiche compatibili con '{rock_type}' non intersecano il boundary iniziale")
                    score -= 8
            else:
                warnings.append(f"Nessuna feature geologica compatibile trovata per: {rock_type}")
                score -= 6
        elif geology_layer and resolved_geology_field:
            if rock_type and not geology_clip_allowed:
                details.append(
                    'Geologia/litologia NON usata per restringere il boundary: '
                    'il cartellino non indica esplicitamente un substrato '
                    'sassicolo/roccioso'
                )
            elif rock_type and not use_geology:
                details.append(
                    'Geologia disponibile ma non usata dal motore ecologico'
                )
            else:
                details.append(
                    'Layer geologia disponibile ma nessun vincolo di roccia presente'
                )

        substrate_query = soil_ph_preference or substrate or (fallback_substrata[0] if fallback_substrata else None)
        if substrate_group == "soil" and not substrate_query:
            substrate_query = self._default_query_for_group("soil", substrate=substrate, soil_ph_preference=soil_ph_preference)
        if soil_layer and soil_field and substrate_query and use_soil:
            matched, matched_count = self._collect_matching_geometry(soil_layer, soil_field, substrate_query, result_geom)

            # GeoLichen 2.3 Stable:
            # Il suolo è un vincolo SOFT: informa lo scoring puntuale,
            # ma non restringe mai il boundary iniziale.
            if matched and not matched.isEmpty():
                details.append(
                    f'Layer suolo/substrato compatibile letto ma NON usato per tagliare il boundary: '
                    f'{substrate_query} ({matched_count} feature)'
                )
            else:
                details.append(
                    f"Layer suolo/substrato: nessuna feature compatibile per '{substrate_query}'; "
                    "boundary non modificato"
                )
                score -= 4
        elif soil_layer and soil_field:
            if substrate_query and not use_soil:
                details.append('Suolo disponibile ma non usato: taxon non interpretato come terricolo/muscicolo')
            else:
                details.append('Layer suolo disponibile ma nessun vincolo di substrato/pH presente')

        tree_query = tree_type
        if substrate_group == "tree" and not tree_query:
            tree_query = self._default_query_for_group("tree", substrate=substrate, tree_type=tree_type)

        if trees_layer and trees_field and tree_query and use_trees:
            matched, matched_count = self._collect_matching_geometry(trees_layer, trees_field, tree_query, result_geom)

            # GeoLichen 2.3 Stable:
            # Foreste/alberi sono vincoli SOFT: danno bonus/diagnostica nello
            # scoring puntuale, ma non tagliano mai il boundary. Assenza di
            # bosco cartografato != assenza di alberi o microhabitat.
            if matched and not matched.isEmpty():
                details.append(
                    f'Layer alberi/boschi compatibile letto ma NON usato per tagliare il boundary: '
                    f'{tree_query} ({matched_count} feature)'
                )
            else:
                details.append(
                    f"Layer alberi/boschi: nessuna feature compatibile per '{tree_query}'; "
                    "boundary non modificato"
                )
                score -= 4
        elif trees_layer and trees_field:
            if tree_query and not use_trees:
                details.append('Alberi disponibili ma non usati: taxon non interpretato come epifita/lignicolo')
            else:
                details.append('Layer alberi disponibile ma nessun vincolo albero/bosco presente')

        score = max(0.0, min(100.0, score - len(blocking_reasons) * 20 - len(warnings) * 2))

        return {
            'geometry': result_geom,
            'details': details,
            'warnings': warnings,
            'blocking_reasons': blocking_reasons,
            'score': score,
            'resolved_geology_field': resolved_geology_field,
            'primary_substrate_group': substrate_group,
        }


    def _substrate_group(self, substrate, fallback_substrata=None, habitat_classes=None):
        """Restituisce il gruppo ecologico primario del substrato.

        Gruppi:
        - rock: saxicoli/rupicoli
        - soil: terricoli/muscicoli
        - tree: epifiti/lignicoli
        """
        values = []
        if substrate:
            values.append(substrate)
        values.extend(fallback_substrata or [])
        values.extend(habitat_classes or [])
        txt = " ".join(str(v).lower() for v in values if v)

        if any(k in txt for k in ["sax", "rupicol", "rocc", "rock", "stone", "calcareo", "siliceo"]):
            return "rock"
        if any(k in txt for k in ["terr", "soil", "suolo", "ground", "musc", "moss", "bryo", "briophy"]):
            return "soil"
        if any(k in txt for k in ["epif", "lign", "bark", "cortecc", "scorza", "tree", "albero", "legno", "wood", "forest", "bosco"]):
            return "tree"
        return None

    def _default_query_for_group(self, group, substrate=None, tree_type=None, soil_ph_preference=None):
        if group == "soil":
            # Se abbiamo una preferenza pH, è più informativa del generico suolo.
            return soil_ph_preference or substrate or "suolo"
        if group == "tree":
            # Se manca la forofita specifica, restringe almeno a bosco/alberi.
            return tree_type or substrate or "bosco"
        return None


    def _resolve_geology_field(self, layer, selected_field):
        if not self._layer_supports_fields(layer):
            return None
        field_names = [f.name() for f in layer.fields()]

        if 'GRUPPO_LITO' in field_names:
            return 'GRUPPO_LITO'

        if selected_field in field_names and self._field_looks_lithologic(layer, selected_field):
            return selected_field

        upper_map = {f.upper(): f for f in field_names}
        for hint in self.GEOLOGY_FIELD_HINTS:
            if hint.upper() in upper_map:
                candidate = upper_map[hint.upper()]
                if candidate.upper() == 'GRUPPO_LITO':
                    return candidate
                if self._field_looks_lithologic(layer, candidate):
                    return candidate

        best_field = None
        best_score = -1
        for f in field_names:
            score = self._score_field_by_values(layer, f)
            if score > best_score:
                best_score = score
                best_field = f
        return best_field

    def _field_looks_lithologic(self, layer, field_name):
        return self._score_field_by_values(layer, field_name) > 0

    def _score_field_by_values(self, layer, field_name, max_samples=50):
        score = 0
        count = 0
        try:
            for feat in layer.getFeatures():
                val = feat[field_name]
                if val in [None, '']:
                    continue
                if field_name.upper() == 'GRUPPO_LITO' and str(val).strip().lower() in ('calcareo', 'siliceo', 'misto'):
                    score += 3
                else:
                    klass = self.lithology_classifier.classify(val)
                    if klass in ('calcareo', 'siliceo', 'misto'):
                        score += 2
                    elif klass == 'altro':
                        text = str(val).lower()
                        if any(k in text for k in ['rocc', 'calc', 'dolom', 'gneiss', 'granit', 'scist', 'arenar', 'quarz', 'marmo']):
                            score += 1
                count += 1
                if count >= max_samples:
                    break
        except Exception:
            return -1
        return score

    def _collect_matching_geometry(self, layer, field_name, needle, boundary_geom_wgs84=None, use_lithology_classifier=False):
        if not self._layer_supports_fields(layer):
            return None, 0
        if field_name not in [f.name() for f in layer.fields()]:
            return None, 0

        boundary_in_layer = self._transform_geometry(boundary_geom_wgs84, self._wgs84(), layer.crs()) if boundary_geom_wgs84 else None
        request = QgsFeatureRequest()
        if boundary_in_layer and not boundary_in_layer.isEmpty():
            request.setFilterRect(boundary_in_layer.boundingBox())

        union_geom = None
        matched_count = 0
        for feat in layer.getFeatures(request):
            try:
                value = feat[field_name]
            except Exception:
                continue
            if value in [None, '']:
                continue

            if use_lithology_classifier:
                haystack = self.lithology_classifier.classify(value)
            else:
                haystack = self._norm(value)

            if self._matches(haystack, needle):
                g = feat.geometry()
                if g is None or g.isEmpty():
                    continue
                if boundary_in_layer and not g.intersects(boundary_in_layer):
                    continue
                g_wgs84 = self._transform_geometry(g, layer.crs(), self._wgs84())
                matched_count += 1
                if union_geom is None:
                    union_geom = QgsGeometry(g_wgs84)
                else:
                    union_geom = union_geom.combine(g_wgs84)

        return union_geom, matched_count

    def _transform_geometry(self, geom, src_crs, dst_crs):
        if geom is None or geom.isEmpty():
            return geom
        if not src_crs.isValid() or not dst_crs.isValid() or src_crs == dst_crs:
            return QgsGeometry(geom)
        transformed = QgsGeometry(geom)
        transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
        transformed.transform(transform)
        return transformed

    def _wgs84(self):
        return QgsCoordinateReferenceSystem('EPSG:4326')

    def _layer_supports_fields(self, layer):
        return layer is not None and layer.type() == QgsMapLayerType.VectorLayer and hasattr(layer, 'fields') and callable(layer.fields)

    def _norm(self, value):
        if value is None:
            return None
        return str(value).strip().lower()

    def _normalize_constraint(self, value):
        if value is None:
            return None
        v = str(value).strip().lower()
        klass = self.lithology_classifier.classify(v)
        if klass in ('calcareo', 'siliceo', 'misto'):
            return klass
        mapping = {
            'roccia calcarea': 'calcareo',
            'rocce calcaree': 'calcareo',
            'calcarea': 'calcareo',
            'roccia silicea': 'siliceo',
            'rocce silicee': 'siliceo',
            'silicea': 'siliceo',
            'mista': 'misto',
            'rocce miste': 'misto',
            'scorza': 'epifita',
            'corteccia': 'epifita',
            'bark': 'epifita',
            'epifita': 'epifita',
            'epifito': 'epifita',
            'roccia': 'saxicolo',
            'suolo': 'terricolo',
            'terricolo': 'terricolo',
            'muscicolo': 'muscicolo',
            'muschio': 'muscicolo',
            'lignicolo': 'lignicolo',
            'legno': 'lignicolo',
            'bosco': 'bosco',
            'albero': 'bosco',
            'acido': 'acid',
            'acid': 'acid',
            'acidico': 'acid',
            'basico': 'basic',
            'basic': 'basic',
            'alcalino': 'basic',
            'neutro': 'neutral',
        }
        return mapping.get(v, v)

    def _matches(self, haystack, needle):
        if not haystack or not needle:
            return False
        if haystack == needle:
            return True
        if needle == 'calcareo' and haystack in ['calcareo', 'misto']:
            return True
        if needle == 'siliceo' and haystack in ['siliceo', 'misto']:
            return True
        if needle == 'misto' and haystack == 'misto':
            return True
        synonyms = {
            'epifita': ['epifita', 'epifit', 'epiph', 'scorza', 'corteccia', 'bark', 'forofita', 'tree', 'albero'],
            'saxicolo': ['saxicolo', 'sax', 'roccia', 'rupicolo'],
            'terricolo': ['terricolo', 'terr', 'soil', 'suolo', 'ground', 'terra'],
            'muscicolo': ['muscicolo', 'muschio', 'moss', 'bryophy', 'briophy'],
            'suolo': ['terricolo', 'terr', 'soil', 'suolo', 'ground', 'terra', 'muscicolo', 'muschio'],
            'lignicolo': ['lignicolo', 'lign', 'wood', 'legno', 'dead wood', 'ceppaia'],
            'bosco': ['bosco', 'forest', 'woodland', 'wood', 'fustaia', 'albero', 'tree', 'arbust', 'latifoglie', 'conifere'],
            'albero': ['bosco', 'forest', 'woodland', 'fustaia', 'albero', 'tree', 'corteccia', 'bark'],
            'legno': ['legno', 'lignicolo', 'wood', 'dead wood', 'ceppaia'],
            'acid': ['acid', 'acido', 'acidico', 'acidoph', 'silic', 'silice', 'torb', 'peat'],
            'basic': ['basic', 'basico', 'alcalino', 'base-rich', 'calcare', 'calcareous', 'calcicol', 'limestone', 'dolomit'],
            'neutral': ['neutral', 'neutro', 'subneutral'],
        }
        values = synonyms.get(needle, [needle])
        return any(v in haystack for v in values)
