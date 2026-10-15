import csv
import math
import os
from dataclasses import dataclass, asdict
from statistics import median

from ._shared_geo_utils import to_float as _shared_to_float


@dataclass
class ValidationRow:
    record_id: str
    reference_latitude: float
    reference_longitude: float
    geolichen_latitude: float
    geolichen_longitude: float
    geolichen_error_m: float
    gbif_latitude: float = None
    gbif_longitude: float = None
    gbif_error_m: float = None
    uncertainty_m: float = None
    reference_inside_uncertainty: bool = None
    gss: float = None
    mci: float = None
    ssi: float = None


class ValidationService:
    """Framework di validazione separato dal motore GeoLichen.

    Legge risultati già prodotti, li confronta con coordinate di riferimento e
    genera metriche descrittive senza modificare GSS, ranking o georeferenziazione.
    """

    @staticmethod
    def read_csv(path):
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            except Exception:
                dialect = csv.excel
            reader = csv.DictReader(handle, dialect=dialect)
            rows = list(reader)
            return list(reader.fieldnames or []), rows

    @staticmethod
    def _to_float(value):
        return _shared_to_float(value)

    @staticmethod
    def haversine_m(lat1, lon1, lat2, lon2):
        radius = 6371008.8
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        return radius * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

    def validate(self, rows, mapping):
        results = []
        skipped = []
        for index, source in enumerate(rows, start=1):
            ref_lat = self._to_float(source.get(mapping.get('reference_latitude')))
            ref_lon = self._to_float(source.get(mapping.get('reference_longitude')))
            geo_lat = self._to_float(source.get(mapping.get('geolichen_latitude')))
            geo_lon = self._to_float(source.get(mapping.get('geolichen_longitude')))
            if None in (ref_lat, ref_lon, geo_lat, geo_lon):
                skipped.append((index, 'Coordinate di riferimento o GeoLichen mancanti/non valide'))
                continue
            if not (-90 <= ref_lat <= 90 and -90 <= geo_lat <= 90 and -180 <= ref_lon <= 180 and -180 <= geo_lon <= 180):
                skipped.append((index, 'Coordinate fuori intervallo'))
                continue

            gbif_lat = self._to_float(source.get(mapping.get('gbif_latitude'))) if mapping.get('gbif_latitude') else None
            gbif_lon = self._to_float(source.get(mapping.get('gbif_longitude'))) if mapping.get('gbif_longitude') else None
            uncertainty = self._to_float(source.get(mapping.get('uncertainty_m'))) if mapping.get('uncertainty_m') else None
            geo_error = self.haversine_m(ref_lat, ref_lon, geo_lat, geo_lon)
            gbif_error = None
            inside = None
            if gbif_lat is not None and gbif_lon is not None:
                gbif_error = self.haversine_m(ref_lat, ref_lon, gbif_lat, gbif_lon)
                if uncertainty is not None and uncertainty >= 0:
                    inside = gbif_error <= uncertainty

            record_id = str(source.get(mapping.get('record_id'), '') or index)
            results.append(ValidationRow(
                record_id=record_id,
                reference_latitude=ref_lat,
                reference_longitude=ref_lon,
                geolichen_latitude=geo_lat,
                geolichen_longitude=geo_lon,
                geolichen_error_m=geo_error,
                gbif_latitude=gbif_lat,
                gbif_longitude=gbif_lon,
                gbif_error_m=gbif_error,
                uncertainty_m=uncertainty,
                reference_inside_uncertainty=inside,
                gss=self._to_float(source.get(mapping.get('gss'))) if mapping.get('gss') else None,
                mci=self._to_float(source.get(mapping.get('mci'))) if mapping.get('mci') else None,
                ssi=self._to_float(source.get(mapping.get('ssi'))) if mapping.get('ssi') else None,
            ))
        return results, skipped

    @staticmethod
    def _stats(values):
        values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        if not values:
            return {}
        n = len(values)
        mean = sum(values) / n
        return {
            'n': n,
            'mae_m': mean,
            'median_m': median(values),
            'rmse_m': math.sqrt(sum(v * v for v in values) / n),
            'max_m': max(values),
            'within_50_pct': 100.0 * sum(v <= 50 for v in values) / n,
            'within_100_pct': 100.0 * sum(v <= 100 for v in values) / n,
            'within_500_pct': 100.0 * sum(v <= 500 for v in values) / n,
            'within_1000_pct': 100.0 * sum(v <= 1000 for v in values) / n,
        }

    def summarize(self, results, skipped_count=0):
        geo = self._stats([r.geolichen_error_m for r in results])
        gbif = self._stats([r.gbif_error_m for r in results])
        coverage_values = [r.reference_inside_uncertainty for r in results if r.reference_inside_uncertainty is not None]
        coverage = None
        if coverage_values:
            coverage = 100.0 * sum(bool(v) for v in coverage_values) / len(coverage_values)
        return {
            'records_validated': len(results),
            'records_skipped': int(skipped_count),
            'geolichen': geo,
            'gbif_center': gbif,
            'uncertainty_coverage_pct': coverage,
            'uncertainty_coverage_n': len(coverage_values),
        }

    @staticmethod
    def export_csv(path, results):
        fieldnames = list(asdict(results[0]).keys()) if results else list(ValidationRow.__dataclass_fields__.keys())
        with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in results:
                writer.writerow(asdict(row))

    @staticmethod
    def export_html(path, summary, results, source_name=''):
        def f(value, digits=1):
            return '—' if value is None else f'{value:.{digits}f}'

        geo = summary.get('geolichen') or {}
        gbif = summary.get('gbif_center') or {}
        lines = [
            '<!doctype html><html><head><meta charset="utf-8">',
            '<title>GeoLichen Validation Report</title>',
            '<style>body{font-family:Arial,sans-serif;margin:28px;color:#222}table{border-collapse:collapse;width:100%;margin:12px 0 24px}th,td{border:1px solid #aaa;padding:6px;text-align:left}th{background:#eee}.num{text-align:right}.ok{font-weight:bold}</style>',
            '</head><body>',
            '<h1>GeoLichen — Validation Report</h1>',
            f'<p><b>Dataset:</b> {os.path.basename(source_name) if source_name else "—"}</p>',
            f'<p><b>Record validati:</b> {summary.get("records_validated", 0)} &nbsp; <b>Scartati:</b> {summary.get("records_skipped", 0)}</p>',
            '<h2>Statistiche del punto GeoLichen</h2>',
            '<table><tr><th>MAE</th><th>Mediana</th><th>RMSE</th><th>Massimo</th><th>≤50 m</th><th>≤100 m</th><th>≤500 m</th><th>≤1 km</th></tr>',
            '<tr>' + ''.join(f'<td class="num">{x}</td>' for x in [f(geo.get('mae_m')), f(geo.get('median_m')), f(geo.get('rmse_m')), f(geo.get('max_m')), f(geo.get('within_50_pct'))+'%', f(geo.get('within_100_pct'))+'%', f(geo.get('within_500_pct'))+'%', f(geo.get('within_1000_pct'))+'%']) + '</tr></table>',
        ]
        if gbif:
            lines.extend([
                '<h2>Statistiche del centro corretto GBIF</h2>',
                '<table><tr><th>MAE</th><th>Mediana</th><th>RMSE</th><th>Massimo</th></tr>',
                '<tr>' + ''.join(f'<td class="num">{x}</td>' for x in [f(gbif.get('mae_m')), f(gbif.get('median_m')), f(gbif.get('rmse_m')), f(gbif.get('max_m'))]) + '</tr></table>',
            ])
        cov = summary.get('uncertainty_coverage_pct')
        lines.append(f'<h2>Copertura dell’incertezza GBIF</h2><p class="ok">{f(cov)}% ({summary.get("uncertainty_coverage_n", 0)} record valutabili)</p>')
        lines.append('<h2>Risultati per record</h2><table><tr><th>ID</th><th>Errore GeoLichen (m)</th><th>Errore centro GBIF (m)</th><th>Incertezza (m)</th><th>Riferimento coperto</th><th>GSS</th><th>MCI</th><th>SSI</th></tr>')
        for row in results:
            covered = 'Sì' if row.reference_inside_uncertainty is True else ('No' if row.reference_inside_uncertainty is False else '—')
            lines.append('<tr>' + ''.join([
                f'<td>{row.record_id}</td>', f'<td class="num">{f(row.geolichen_error_m)}</td>', f'<td class="num">{f(row.gbif_error_m)}</td>',
                f'<td class="num">{f(row.uncertainty_m)}</td>', f'<td>{covered}</td>', f'<td class="num">{f(row.gss,2)}</td>',
                f'<td class="num">{f(row.mci,1)}</td>', f'<td class="num">{f(row.ssi,1)}</td>'
            ]) + '</tr>')
        lines.append('</table><p><i>Il framework legge risultati già prodotti e non modifica il motore GeoLichen.</i></p></body></html>')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines))
