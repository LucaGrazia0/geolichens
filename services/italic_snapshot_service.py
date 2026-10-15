import json
import os
from datetime import datetime, timezone

from .storage_service import profile_data_path


class ItalicSnapshotService:
    """Salva una copia locale del profilo ITALIC usato per una georeferenziazione.

    ITALIC è una risorsa dinamica: i profili ecologici possono cambiare nel tempo.
    Questo servizio registra lo stato informativo effettivamente usato dal plugin,
    così il risultato resta verificabile e riproducibile anche se ITALIC viene aggiornato.
    """

    def __init__(self, snapshot_path=None):
        self.snapshot_path = snapshot_path or profile_data_path("italic_snapshots.json")

    def make_snapshot(self, profile, queried_name=None):
        profile = profile or {}
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "snapshot_date_utc": now,
            "source": "ITALIC 8.0 dynamic query",
            "queried_name": queried_name or profile.get("queried_name") or profile.get("original_name") or profile.get("scientific_name"),
            "scientific_name": profile.get("scientific_name"),
            "accepted_name": profile.get("accepted_name"),
            "matched_name": profile.get("matched_name"),
            "taxon_id": profile.get("taxon_id"),
            "nomenclature_status": profile.get("nomenclature_status"),
            "substrata": profile.get("substrata") or [],
            "habitat": profile.get("habitat") or [],
            "rock_type": profile.get("rock_type"),
            "italic_altitude_class_min": profile.get("italic_altitude_class_min"),
            "italic_altitude_class_max": profile.get("italic_altitude_class_max"),
            "altitudinal_distribution_min": profile.get("altitudinal_distribution_min"),
            "altitudinal_distribution_max": profile.get("altitudinal_distribution_max"),
            "altitudinal_distribution_source": profile.get("altitudinal_distribution_source"),
            "ecology_traits": profile.get("ecology_traits"),
            "diagnostic": profile.get("diagnostic"),
            "diagnostic_info": profile.get("diagnostic_info"),
            "cache_status": profile.get("cache_status"),
        }
        return snapshot

    def attach_snapshot(self, profile, queried_name=None):
        if profile is None:
            profile = {}
        snapshot = self.make_snapshot(profile, queried_name=queried_name)
        profile["italic_snapshot"] = snapshot
        profile["italic_snapshot_date_utc"] = snapshot.get("snapshot_date_utc")
        return profile

    def save_snapshot(self, profile, queried_name=None):
        snapshot = self.make_snapshot(profile, queried_name=queried_name)
        try:
            existing = []
            if os.path.exists(self.snapshot_path):
                with open(self.snapshot_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        existing = data
            existing.append(snapshot)
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            return snapshot
        except Exception as exc:
            snapshot["snapshot_save_error"] = str(exc)
            return snapshot
