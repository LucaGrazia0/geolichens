import csv
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class InteractiveValidationResult:
    timestamp_utc: str
    record_id: str
    reference_latitude: float
    reference_longitude: float
    geolichen_latitude: float
    geolichen_longitude: float
    geolichen_error_m: float
    gbif_latitude: float | None
    gbif_longitude: float | None
    gbif_error_m: float | None
    uncertainty_m: float | None
    error_uncertainty_ratio: float | None
    reference_inside_uncertainty: bool | None
    reference_altitude_m: float | None
    geolichen_altitude_m: float | None
    altitude_error_m: float | None
    gss: float | None
    mci: float | None
    ssi: float | None
    candidate_rank: int | None


class InteractiveValidationService:
    """Valida un singolo risultato senza modificare il motore GeoLichen."""

    EARTH_RADIUS_M = 6371008.8

    @classmethod
    def distance_m(cls, lat1, lon1, lat2, lon2):
        values = [float(lat1), float(lon1), float(lat2), float(lon2)]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Coordinate non finite")
        p1, p2 = math.radians(values[0]), math.radians(values[2])
        dp = math.radians(values[2] - values[0])
        dl = math.radians(values[3] - values[1])
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        return cls.EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

    @staticmethod
    def _optional_float(value):
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except Exception:
            return None

    def validate(self, *, reference_latitude, reference_longitude,
                 geolichen_latitude, geolichen_longitude,
                 gbif_latitude=None, gbif_longitude=None,
                 uncertainty_m=None, reference_altitude_m=None,
                 geolichen_altitude_m=None, gss=None, mci=None, ssi=None,
                 candidate_rank=None, record_id=""):
        ref_lat = float(reference_latitude)
        ref_lon = float(reference_longitude)
        geo_lat = float(geolichen_latitude)
        geo_lon = float(geolichen_longitude)
        if not (-90 <= ref_lat <= 90 and -180 <= ref_lon <= 180):
            raise ValueError("Le coordinate di riferimento non sono valide (WGS84).")

        geo_error = self.distance_m(ref_lat, ref_lon, geo_lat, geo_lon)
        gbif_lat = self._optional_float(gbif_latitude)
        gbif_lon = self._optional_float(gbif_longitude)
        gbif_error = None
        if gbif_lat is not None and gbif_lon is not None:
            gbif_error = self.distance_m(ref_lat, ref_lon, gbif_lat, gbif_lon)

        unc = self._optional_float(uncertainty_m)
        ratio = None
        inside = None
        if unc is not None and unc > 0:
            ratio = geo_error / unc
            inside = geo_error <= unc

        ref_alt = self._optional_float(reference_altitude_m)
        geo_alt = self._optional_float(geolichen_altitude_m)
        alt_error = abs(ref_alt - geo_alt) if ref_alt is not None and geo_alt is not None else None

        return InteractiveValidationResult(
            timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            record_id=str(record_id or "").strip(),
            reference_latitude=ref_lat,
            reference_longitude=ref_lon,
            geolichen_latitude=geo_lat,
            geolichen_longitude=geo_lon,
            geolichen_error_m=geo_error,
            gbif_latitude=gbif_lat,
            gbif_longitude=gbif_lon,
            gbif_error_m=gbif_error,
            uncertainty_m=unc,
            error_uncertainty_ratio=ratio,
            reference_inside_uncertainty=inside,
            reference_altitude_m=ref_alt,
            geolichen_altitude_m=geo_alt,
            altitude_error_m=alt_error,
            gss=self._optional_float(gss),
            mci=self._optional_float(mci),
            ssi=self._optional_float(ssi),
            candidate_rank=int(candidate_rank) if candidate_rank is not None else None,
        )

    @staticmethod
    def append_csv(path, result):
        row = asdict(result)
        exists = os.path.exists(path) and os.path.getsize(path) > 0
        with open(path, "a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
            if not exists:
                writer.writeheader()
            writer.writerow(row)
