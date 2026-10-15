"""Provenance and decision-log utilities for GeoLichen Phase 11.3.

The service is strictly read-only.  It records only evidence that is already
available in the selected candidate, LocalityContext and uncertainty result.
When a source or processing step cannot be demonstrated from those values it
is explicitly marked as not traced instead of being guessed.
"""

from datetime import datetime, timezone


class ProvenanceReportingService:
    STATUS_USED = "Utilizzata"
    STATUS_NOT_USED = "Non utilizzata"
    STATUS_UNAVAILABLE = "Non disponibile"
    STATUS_NOT_TRACED = "Non tracciato"

    @staticmethod
    def _context_value(context, name, default=None):
        try:
            return getattr(context, name, default)
        except Exception:
            return default

    @staticmethod
    def _present(value):
        return value not in (None, "", [], {}, ())

    @staticmethod
    def _as_text(value):
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _first_present(cls, *values):
        """Restituisce il primo valore realmente valorizzato, senza inventare fallback."""
        for value in values:
            if cls._present(value):
                return value
        return None

    def _source_row(self, component, source="", detail="", status=None, evidence=""):
        source = self._as_text(source)
        detail = self._as_text(detail)
        evidence = self._as_text(evidence)
        if status is None:
            status = self.STATUS_USED if source else self.STATUS_UNAVAILABLE
        if not source:
            if status == self.STATUS_USED:
                source = "Calcolata internamente da GeoLichen"
            elif status == self.STATUS_NOT_USED:
                source = "Non utilizzata nel risultato corrente"
            elif status == self.STATUS_NOT_TRACED:
                source = "Sorgente non registrata"
            else:
                source = "Non disponibile"
        if not detail:
            detail = "Non applicabile" if status == self.STATUS_NOT_USED else "Dettaglio non registrato"
        if not evidence:
            evidence = "Nessuna evidenza tecnica registrata"
        return {
            "component": component,
            "source": source,
            "detail": detail,
            "status": status,
            "evidence": evidence,
        }

    @staticmethod
    def _step(stage, status, detail="", count=None, input_count=None, output_count=None, duration_ms=None):
        return {
            "stage": stage,
            "status": status,
            "detail": str(detail or "").strip(),
            "count": count,
            "input_count": input_count,
            "output_count": output_count,
            # Phase 11.3 does not invent timings: populated only if a future
            # pipeline explicitly records them.
            "duration_ms": duration_ms,
        }

    def build_provenance(self, selected_candidate, candidates, locality_context=None, uncertainty_info=None):
        selected_candidate = selected_candidate or {}
        env = selected_candidate.get("env") or {}
        constraints = selected_candidate.get("constraints") or env.get("constraints") or {}
        uncertainty_info = uncertainty_info or {}
        candidates = list(candidates or [])

        sources = []

        slge_active = bool(uncertainty_info.get("slge_active"))
        slge_feature_type = uncertainty_info.get("slge_feature_type")
        slge_expected_geometry = uncertainty_info.get("slge_expected_geometry")
        slge_actual_geometry = uncertainty_info.get("slge_documented_geometry_type")
        slge_source = uncertainty_info.get("slge_documented_source")
        slge_method = uncertainty_info.get("slge_documented_method")
        slge_identifier = uncertainty_info.get("slge_documented_source_identifier")
        slge_gci = uncertainty_info.get("slge_geometry_confidence")
        slge_gci_class = uncertainty_info.get("slge_geometry_confidence_class")
        slge_semantic_confidence = uncertainty_info.get("slge_semantic_confidence")
        slge_review = bool(uncertainty_info.get("slge_requires_review"))
        try:
            slge_gci_text = f"{float(slge_gci) * 100.0:.0f}% ({slge_gci_class or 'non classificato'})"
        except Exception:
            slge_gci_text = "Non disponibile"
        sources.append(self._source_row(
            "SLGE — interpretazione semantica",
            "Semantic Locality Parser" if slge_active else "",
            f"feature={slge_feature_type}; geometria attesa={slge_expected_geometry}; regola={uncertainty_info.get('slge_matched_rule')}",
            self.STATUS_USED if slge_active else self.STATUS_NOT_TRACED,
            f"semantic_confidence={slge_semantic_confidence}" if self._present(slge_semantic_confidence) else "",
        ))
        gre_active = bool(uncertainty_info.get("gre_active"))
        gre_resolver = uncertainty_info.get("gre_resolver")
        gre_decision = uncertainty_info.get("gre_decision")
        gre_source = uncertainty_info.get("gre_source")
        gre_method = uncertainty_info.get("gre_method")
        gre_geometry_type = uncertainty_info.get("gre_geometry_type")
        gre_confidence = uncertainty_info.get("gre_confidence")
        gre_fallback = bool(uncertainty_info.get("gre_fallback_used"))
        try:
            gre_confidence_text = f"{float(gre_confidence) * 100.0:.0f}%"
        except Exception:
            gre_confidence_text = "Non disponibile"
        gre_status = self.STATUS_USED if gre_active else self.STATUS_NOT_TRACED
        if gre_active and gre_fallback:
            gre_status = "Utilizzata con fallback"
        sources.append(self._source_row(
            "GRE — Geometry Resolution Engine",
            gre_resolver or ("GeometryResolutionEngine" if gre_active else ""),
            (
                f"decisione={gre_decision or '-'}; tipo={gre_geometry_type or '-'}; "
                f"sorgente={gre_source or '-'}; metodo={gre_method or '-'}"
            ),
            gre_status,
            f"confidence={gre_confidence_text}; fallback={gre_fallback}",
        ))
        sources.append(self._source_row(
            "SLGE — geometria documentale",
            slge_source,
            f"metodo={slge_method}; tipo={slge_actual_geometry}; id={slge_identifier or '-'}",
            self.STATUS_USED if uncertainty_info.get("slge_documented_geometry_used") else self.STATUS_UNAVAILABLE,
            "Usata esclusivamente per centro corretto e coordinateUncertaintyInMeters",
        ))
        sources.append(self._source_row(
            "SLGE — Geometry Confidence Index",
            "GeometryConfidenceService" if slge_active else "",
            slge_gci_text,
            self.STATUS_USED if self._present(slge_gci) else self.STATUS_UNAVAILABLE,
            "; ".join((uncertainty_info.get("slge_geometry_confidence_reasons") or [])[:3]),
        ))
        terrain_used = bool(uncertainty_info.get("terrain_reconstruction_used"))
        terrain_available = bool(uncertainty_info.get("terrain_reconstruction_available"))
        terrain_status = self.STATUS_USED if terrain_used else (self.STATUS_NOT_USED if terrain_available else self.STATUS_UNAVAILABLE)
        terrain_area = uncertainty_info.get("terrain_polygon_area_km2")
        terrain_summit = uncertainty_info.get("terrain_summit_elevation_m")
        terrain_validation = uncertainty_info.get("terrain_validation_confidence")
        sources.append(self._source_row(
            "Terrain Reconstruction — poligono documentale",
            uncertainty_info.get("terrain_dem_layer_name") or uncertainty_info.get("terrain_dem_source") or "Terrain Reconstruction Engine",
            (
                f"decisione={uncertainty_info.get('terrain_decision') or '-'}; "
                f"area_km2={terrain_area if self._present(terrain_area) else '-'}; "
                f"summit_m={terrain_summit if self._present(terrain_summit) else '-'}"
            ),
            terrain_status,
            (
                f"validation_confidence={terrain_validation}; "
                f"fallback={bool(uncertainty_info.get('terrain_fallback_used'))}; "
                f"manual_review={bool(uncertainty_info.get('terrain_manual_review_required'))}"
            ),
        ))
        sources.append(self._source_row(
            "SLGE — geometria operativa di ricerca",
            uncertainty_info.get("slge_search_source"),
            (
                f"strategia={uncertainty_info.get('slge_search_strategy')}; "
                f"espansa={bool(uncertainty_info.get('slge_search_expanded'))}; "
                f"ritagliata={bool(uncertainty_info.get('slge_search_clipped'))}; "
                f"filtri={', '.join(uncertainty_info.get('slge_search_filters') or []) or '-'}"
            ),
            self.STATUS_USED if slge_active else self.STATUS_NOT_TRACED,
            "Separata dalla geometria documentale",
        ))

        dem_source = env.get("dem_source")
        altitude = env.get("altitude")
        sources.append(self._source_row(
            "Quota / modello digitale del terreno",
            dem_source,
            "Campionamento della quota sul candidato selezionato" if self._present(altitude) else "Nessun valore di quota tracciato",
            self.STATUS_USED if self._present(dem_source) or self._present(altitude) else self.STATUS_UNAVAILABLE,
            f"altitude={altitude}" if self._present(altitude) else "",
        ))

        # GeoLichen Ecological Context Refactor: separa sempre il dato osservato
        # sul cartellino, il profilo generale del taxon e la decisione del resolver.
        substrate_group = self._first_present(
            env.get("substrate_group"), constraints.get("substrate_group")
        ) or "unknown"
        substrate_raw = self._first_present(
            env.get("substrate_raw"), constraints.get("substrate_raw"),
            env.get("record_substrate"), constraints.get("record_substrate"),
            env.get("substrate_observed")
        )
        substrate_source = self._first_present(
            env.get("substrate_source"), constraints.get("substrate_source")
        )
        substrate_locked = bool(self._first_present(
            env.get("substrate_locked"), constraints.get("substrate_locked")
        ))
        substrate_confidence = self._first_present(
            env.get("substrate_confidence"), constraints.get("substrate_confidence")
        )
        substrate_reason = self._first_present(
            env.get("substrate_resolution_reason"),
            constraints.get("substrate_resolution_reason")
        )
        layer_decision = self._first_present(
            env.get("layer_decision"), constraints.get("layer_decision")
        ) or {}
        if not isinstance(layer_decision, dict):
            layer_decision = {}
        primary_pipeline = self._first_present(
            layer_decision.get("primary"),
            layer_decision.get("primary_layer"),
            env.get("ecological_pipeline"),
            constraints.get("ecological_pipeline")
        )

        label_status = self.STATUS_USED if self._present(substrate_raw) else self.STATUS_NOT_TRACED
        sources.append(self._source_row(
            "Substrato del reperto — osservazione",
            substrate_source if self._present(substrate_raw) else "",
            substrate_raw,
            label_status,
            "Valore osservato sul cartellino; non è un profilo ecologico generale",
        ))

        italic_source = env.get("italic_source") or env.get("taxon_source")
        italic_version = env.get("italic_version") or env.get("italic_snapshot")
        italic_evidence = env.get("taxon") or env.get("scientific_name") or env.get("environmental_group")
        italic_available = self._present(italic_source) or self._present(italic_evidence)
        italic_role = "supporto ecologico/fallback; non sovrascrive un substrato locked" if substrate_locked else "supporto ecologico e possibile fallback"
        sources.append(self._source_row(
            "Profilo ecologico ITALIC del taxon",
            italic_source or ("ITALIC / snapshot GeoLichen" if italic_available else ""),
            f"versione={italic_version or '-'}; ruolo={italic_role}",
            self.STATUS_USED if italic_available else self.STATUS_NOT_TRACED,
            italic_evidence,
        ))

        resolver_traced = substrate_group != "unknown" or self._present(substrate_source) or self._present(substrate_reason)
        confidence_text = ""
        if self._present(substrate_confidence):
            try:
                confidence_text = f"{float(substrate_confidence) * 100.0:.0f}%"
            except Exception:
                confidence_text = str(substrate_confidence)
        sources.append(self._source_row(
            "Decisione finale — Substrate Resolution Engine",
            "SubstrateResolutionService" if resolver_traced else "",
            (
                f"gruppo={substrate_group}; pipeline={primary_pipeline or '-'}; "
                f"locked={substrate_locked}; confidence={confidence_text or '-'}"
            ),
            self.STATUS_USED if resolver_traced else self.STATUS_NOT_TRACED,
            substrate_reason or "Decisione non ricostruibile dai valori persistiti",
        ))

        rock_value = env.get("rock_type") or env.get("rock_raw")
        rock_source = env.get("geology_source") or env.get("lithology_source") or env.get("rock_source")
        sources.append(self._source_row(
            "Litologia",
            rock_source,
            rock_value,
            self.STATUS_USED if self._present(rock_value) else self.STATUS_NOT_USED,
            "rock_type/rock_raw" if self._present(rock_value) else "",
        ))

        soil_value = env.get("soil_ph") or env.get("ph_class") or env.get("soil_type")
        soil_source = env.get("soil_source")
        sources.append(self._source_row(
            "Suolo / pH",
            soil_source,
            soil_value,
            self.STATUS_USED if self._present(soil_value) else self.STATUS_NOT_USED,
            "soil_ph/ph_class/soil_type" if self._present(soil_value) else "",
        ))

        habitat_value = env.get("habitat") or env.get("habitat_class")
        habitat_source = env.get("habitat_source")
        sources.append(self._source_row(
            "Habitat",
            habitat_source,
            habitat_value,
            self.STATUS_USED if self._present(habitat_value) else self.STATUS_NOT_USED,
            "habitat/habitat_class" if self._present(habitat_value) else "",
        ))

        forest_value = env.get("forest_type") or env.get("tree") or env.get("forest_dist_m")
        forest_source = env.get("forest_source")
        forest_detail = env.get("forest_type") or env.get("tree")
        if self._present(env.get("forest_dist_m")):
            forest_detail = f"{forest_detail}; distanza {env.get('forest_dist_m')} m" if forest_detail else f"Distanza {env.get('forest_dist_m')} m"
        sources.append(self._source_row(
            "Copertura forestale / alberi",
            forest_source,
            forest_detail,
            self.STATUS_USED if self._present(forest_value) else self.STATUS_NOT_USED,
            "forest_type/tree/forest_dist_m" if self._present(forest_value) else "",
        ))

        access_value = env.get("accessibility_macro_score")
        access_source = env.get("accessibility_source")
        access_detail = env.get("trail_dist_m") or env.get("path_dist_m") or env.get("accessibility_details")
        sources.append(self._source_row(
            "Accessibilità",
            access_source or ("Motore di accessibilità GeoLichen" if self._present(access_value) else ""),
            access_detail,
            self.STATUS_USED if self._present(access_value) else self.STATUS_NOT_USED,
            f"accessibility_macro_score={access_value}" if self._present(access_value) else "",
        ))

        geocoded_center = self._context_value(locality_context, "geocoded_center", None)
        geocoder_source = uncertainty_info.get("georeferenceSources")
        sources.append(self._source_row(
            "Toponimo / geocodifica",
            geocoder_source,
            self._context_value(locality_context, "search_name", ""),
            self.STATUS_USED if self._present(geocoded_center) else self.STATUS_NOT_TRACED,
            "LocalityContext.geocoded_center" if self._present(geocoded_center) else "",
        ))

        original_extent = self._context_value(locality_context, "original_locality_extent", None)
        boundary_source = self._context_value(locality_context, "boundary_source", "")
        geometry_method = self._context_value(locality_context, "locality_geometry_method", "")
        sources.append(self._source_row(
            "Confine / estensione della località",
            boundary_source,
            geometry_method,
            self.STATUS_USED if self._present(original_extent) else self.STATUS_UNAVAILABLE,
            "LocalityContext.original_locality_extent" if self._present(original_extent) else "",
        ))

        water_evidence = env.get("water_excluded") or env.get("water_filter_applied") or env.get("hydro_mask_source")
        sources.append(self._source_row(
            "Maschera acqua / idrografia",
            env.get("hydro_mask_source"),
            "Esclusione delle superfici d’acqua" if water_evidence else "Il risultato corrente non registra una prova esplicita dell’applicazione della maschera",
            self.STATUS_USED if water_evidence else self.STATUS_NOT_TRACED,
            "water_excluded/water_filter_applied/hydro_mask_source" if water_evidence else "",
        ))

        protocol = uncertainty_info.get("georeferenceProtocol")
        center_method = uncertainty_info.get("corrected_center_method")
        sources.append(self._source_row(
            "Protocollo di georeferenziazione GBIF",
            protocol,
            center_method,
            self.STATUS_USED if self._present(protocol) or self._present(uncertainty_info.get("coordinateUncertaintyInMeters")) else self.STATUS_UNAVAILABLE,
            "georeferenceProtocol / coordinateUncertaintyInMeters",
        ))

        decision_log = []
        decision_log.append(self._step(
            "Record ricevuto", "Completato",
            "Comune, località e attributi del record passati alla pipeline"
        ))

        decision_log.append(self._step(
            "Substrato osservato sul cartellino",
            "Completato" if self._present(substrate_raw) else "Non tracciato",
            f"valore={substrate_raw}; sorgente={substrate_source or '-'}" if self._present(substrate_raw) else "Nessun valore osservato persistito"
        ))
        decision_log.append(self._step(
            "Risoluzione centralizzata del substrato",
            "Completato" if resolver_traced else "Non tracciato",
            (
                f"gruppo={substrate_group}; locked={substrate_locked}; "
                f"confidence={confidence_text or '-'}; motivo={substrate_reason or '-'}"
            )
        ))
        decision_log.append(self._step(
            "Selezione pipeline ecologica",
            "Completato" if self._present(primary_pipeline) else ("Parziale" if resolver_traced else "Non tracciato"),
            f"pipeline={primary_pipeline or '-'}; gruppo={substrate_group}"
        ))

        locality_type = self._context_value(locality_context, "locality_type", "unknown")
        classification_confidence = self._context_value(locality_context, "classification_confidence", None)
        classification_ok = locality_type not in (None, "", "unknown")
        decision_log.append(self._step(
            "Località interpretata",
            "Completato" if classification_ok else "Parziale",
            f"tipo={locality_type}; confidenza={classification_confidence}" if classification_confidence is not None else f"tipo={locality_type}"
        ))

        decision_log.append(self._step(
            "SLGE — parsing semantico",
            "Completato" if slge_active else "Non tracciato",
            f"feature={slge_feature_type}; attesa={slge_expected_geometry}; confidenza={slge_semantic_confidence}"
        ))
        decision_log.append(self._step(
            "GRE — Geometry Resolution Engine",
            ("Fallback" if gre_fallback else "Completato") if gre_active else "Non tracciato",
            f"resolver={gre_resolver}; decisione={gre_decision}; sorgente={gre_source}; tipo={gre_geometry_type}"
        ))
        decision_log.append(self._step(
            "SLGE — risoluzione geometria documentale",
            "Verifica richiesta" if slge_review else ("Completato" if uncertainty_info.get("slge_documented_geometry_used") else "Non disponibile"),
            f"sorgente={slge_source}; metodo={slge_method}; tipo={slge_actual_geometry}"
        ))
        decision_log.append(self._step(
            "SLGE — calcolo GCI",
            "Completato" if self._present(slge_gci) else "Non disponibile",
            slge_gci_text
        ))
        decision_log.append(self._step(
            "SLGE — separazione geometria di ricerca",
            "Completato" if slge_active else "Non tracciato",
            f"strategia={uncertainty_info.get('slge_search_strategy')}; sorgente={uncertainty_info.get('slge_search_source')}"
        ))

        decision_log.append(self._step(
            "Geocodifica",
            "Completato" if self._present(geocoded_center) else "Non tracciato",
            self._context_value(locality_context, "search_name", "")
        ))

        decision_log.append(self._step(
            "Estensione geografica iniziale",
            "Completato" if self._present(original_extent) else "Non disponibile",
            geometry_method or self._context_value(locality_context, "search_strategy", "")
        ))

        offset_applied = bool(self._context_value(locality_context, "locality_geometry_applied", False))
        requires_verification = bool(self._context_value(locality_context, "locality_geometry_requires_verification", False))
        offset_spec = self._context_value(locality_context, "offset_spec", None)
        if self._present(offset_spec):
            offset_status = "Verifica richiesta" if requires_verification else ("Completato" if offset_applied else "Non applicato")
            offset_detail = self._context_value(locality_context, "locality_geometry_reason", "") or geometry_method
        else:
            offset_status = "Non applicabile"
            offset_detail = "Nessun offset esplicito riconosciuto"
        decision_log.append(self._step("Geometria avanzata della località", offset_status, offset_detail))

        decision_log.append(self._step(
            "Campionamento DEM",
            "Completato" if self._present(altitude) else "Non disponibile",
            f"{dem_source or 'sorgente non tracciata'}; quota={altitude}" if self._present(altitude) else ""
        ))

        decision_log.append(self._step(
            "Maschera acqua",
            "Completato" if water_evidence else "Non tracciato",
            "Superfici d’acqua escluse" if water_evidence else "Nessun flag di esecuzione disponibile nel risultato"
        ))

        environmental_evidence = any(self._present(v) for v in (rock_value, soil_value, habitat_value, forest_value))
        decision_log.append(self._step(
            "Vincoli ambientali",
            "Completato" if environmental_evidence else "Parziale",
            (
                f"pipeline={primary_pipeline or '-'}; gruppo substrato={substrate_group}; "
                "litologia, suolo/pH, habitat e copertura forestale letti solo quando pertinenti e disponibili"
            )
        ))

        decision_log.append(self._step(
            "Generazione e valutazione dei candidati",
            "Completato" if candidates else "Non disponibile",
            "Punti con score GSS",
            count=len(candidates), output_count=len(candidates)
        ))

        selected_score = selected_candidate.get("score")
        decision_log.append(self._step(
            "Calcolo GSS e ranking",
            "Completato" if self._present(selected_score) else "Non disponibile",
            f"Rank {selected_candidate.get('rank') or 1}; GSS {float(selected_score or 0):.2f}" if self._present(selected_score) else "",
            count=1
        ))

        mci = uncertainty_info.get("model_confidence_index")
        decision_log.append(self._step(
            "Calcolo MCI",
            "Completato" if self._present(mci) else "Non disponibile",
            f"MCI={mci}%" if self._present(mci) else ""
        ))

        ssi = uncertainty_info.get("solution_stability_index")
        equivalent = uncertainty_info.get("plausible_alternative_count")
        main_cluster = uncertainty_info.get("ssi_main_cluster_count")
        decision_log.append(self._step(
            "Clusterizzazione e SSI",
            "Completato" if self._present(ssi) else "Non disponibile",
            (
                f"Candidati valutati={len(candidates)}; equivalenti={equivalent}; "
                f"cluster principale={main_cluster}; SSI={ssi}%"
            ) if self._present(ssi) else "",
            count=equivalent, input_count=len(candidates), output_count=main_cluster
        ))

        corrected_ok = self._present(uncertainty_info.get("corrected_center_lon")) and self._present(uncertainty_info.get("corrected_center_lat"))
        decision_log.append(self._step(
            "Centro corretto GBIF",
            "Completato" if corrected_ok else "Non disponibile",
            center_method or ""
        ))

        dwc_required = ("decimalLatitude", "decimalLongitude", "geodeticDatum", "coordinateUncertaintyInMeters", "georeferenceProtocol")
        dwc_populated = sum(1 for key in dwc_required if self._present(uncertainty_info.get(key)))
        decision_log.append(self._step(
            "Metadati Darwin Core",
            "Completato" if dwc_populated == len(dwc_required) else ("Parziale" if dwc_populated else "Non disponibile"),
            f"{dwc_populated}/{len(dwc_required)} campi essenziali compilati"
        ))

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plugin": "GeoLichen",
            "phase": "Ecological Context Refactor",
            "sources": sources,
            "decision_log": decision_log,
            # Kept for backward compatibility with Phase 11.2 exports.
            "timeline": decision_log,
            "timing_note": "I tempi non vengono mostrati perché la pipeline corrente non registra ancora misure temporali affidabili.",
            "substrate_resolution": {
                "observed_value": substrate_raw,
                "group": substrate_group,
                "source": substrate_source,
                "locked": substrate_locked,
                "confidence": substrate_confidence,
                "reason": substrate_reason,
                "primary_pipeline": primary_pipeline,
                "italic_role": italic_role,
                "italic_overrode_locked_value": False if substrate_locked else None,
            },
            "slge": {
                "active": slge_active,
                "feature_type": slge_feature_type,
                "expected_geometry": slge_expected_geometry,
                "actual_geometry": slge_actual_geometry,
                "semantic_confidence": slge_semantic_confidence,
                "matched_rule": uncertainty_info.get("slge_matched_rule"),
                "documented_source": slge_source,
                "documented_source_identifier": slge_identifier,
                "documented_method": slge_method,
                "documented_estimated": bool(uncertainty_info.get("slge_documented_estimated")),
                "geometry_confidence_index": slge_gci,
                "geometry_confidence_class": slge_gci_class,
                "geometry_confidence_reasons": list(uncertainty_info.get("slge_geometry_confidence_reasons") or []),
                "requires_review": slge_review,
                "search_strategy": uncertainty_info.get("slge_search_strategy"),
                "search_source": uncertainty_info.get("slge_search_source"),
                "search_expanded": bool(uncertainty_info.get("slge_search_expanded")),
                "search_clipped": bool(uncertainty_info.get("slge_search_clipped")),
                "search_filters": list(uncertainty_info.get("slge_search_filters") or []),
            },
            "gre": {
                "active": gre_active,
                "resolver": gre_resolver,
                "decision": gre_decision,
                "source": gre_source,
                "method": gre_method,
                "geometry_type": gre_geometry_type,
                "confidence": gre_confidence,
                "fallback_used": gre_fallback,
            },
            "terrain_reconstruction": {
                "available": bool(uncertainty_info.get("terrain_reconstruction_available")),
                "used": bool(uncertainty_info.get("terrain_reconstruction_used")),
                "selected_source": uncertainty_info.get("terrain_selected_source"),
                "decision": uncertainty_info.get("terrain_decision"),
                "decision_confidence": uncertainty_info.get("terrain_decision_confidence"),
                "validation_confidence": uncertainty_info.get("terrain_validation_confidence"),
                "fallback_used": bool(uncertainty_info.get("terrain_fallback_used")),
                "manual_review_required": bool(uncertainty_info.get("terrain_manual_review_required")),
                "polygon_area_m2": uncertainty_info.get("terrain_polygon_area_m2"),
                "polygon_area_km2": uncertainty_info.get("terrain_polygon_area_km2"),
                "polygon_compactness": uncertainty_info.get("terrain_polygon_compactness"),
                "polygon_max_distance_m": uncertainty_info.get("terrain_polygon_max_distance_m"),
                "summit_elevation_m": uncertainty_info.get("terrain_summit_elevation_m"),
                "summit_prominence_m": uncertainty_info.get("terrain_summit_prominence_m"),
                "dem_layer_name": uncertainty_info.get("terrain_dem_layer_name"),
                "dem_source": uncertainty_info.get("terrain_dem_source"),
                "dem_resolution_m": uncertainty_info.get("terrain_dem_resolution_m"),
                "dem_coverage_ratio": uncertainty_info.get("terrain_dem_coverage_ratio"),
            },
            "locality": {
                "municipality": self._context_value(locality_context, "municipality", ""),
                "locality": self._context_value(locality_context, "locality", ""),
                "locality_type": locality_type,
                "geometry_type": self._context_value(locality_context, "geometry_type", "unknown"),
                "classification_confidence": classification_confidence or 0.0,
                "geometry_method": geometry_method,
                "requires_verification": requires_verification,
            },
            "darwin_core": {key: uncertainty_info.get(key) for key in (
                "decimalLatitude", "decimalLongitude", "geodeticDatum",
                "coordinateUncertaintyInMeters", "coordinatePrecision",
                "pointRadiusSpatialFit", "footprintWKT", "footprintSRS",
                "georeferencedBy", "georeferencedDate", "georeferenceProtocol",
                "georeferenceSources", "georeferenceVerificationStatus",
                "georeferenceRemarks",
            )},
        }
