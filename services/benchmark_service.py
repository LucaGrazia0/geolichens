import csv
import html
import math
import os
from dataclasses import dataclass, asdict
from statistics import median

from ._shared_geo_utils import to_float as _shared_to_float


@dataclass
class BenchmarkRecord:
    record_id: str
    method: str
    reference_latitude: float
    reference_longitude: float
    latitude: float
    longitude: float
    error_m: float
    runtime_s: float = None


class BenchmarkService:
    """Confronto riproducibile fra GeoLichen e metodi esterni.

    Il servizio non esegue software esterni: confronta coordinate già prodotte
    da ciascun metodo con un medesimo gold standard.
    """

    THRESHOLDS_M = (50, 100, 500, 1000)

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
            return list(reader.fieldnames or []), list(reader)

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

    def benchmark(self, rows, base_mapping, methods):
        """Return long-format results, skipped rows and per-record winner data.

        methods: list of dicts {name, latitude, longitude, runtime_s(optional)}.
        """
        results = []
        skipped = []
        winner_rows = []

        for index, source in enumerate(rows, start=1):
            ref_lat = self._to_float(source.get(base_mapping.get('reference_latitude')))
            ref_lon = self._to_float(source.get(base_mapping.get('reference_longitude')))
            if ref_lat is None or ref_lon is None or not (-90 <= ref_lat <= 90 and -180 <= ref_lon <= 180):
                skipped.append((index, 'Coordinate gold standard mancanti o non valide'))
                continue

            record_id = str(source.get(base_mapping.get('record_id'), '') or index)
            record_results = []
            for method in methods:
                name = str(method.get('name') or '').strip()
                lat_field = method.get('latitude')
                lon_field = method.get('longitude')
                if not name or not lat_field or not lon_field:
                    continue
                lat = self._to_float(source.get(lat_field))
                lon = self._to_float(source.get(lon_field))
                if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                runtime = self._to_float(source.get(method.get('runtime_s'))) if method.get('runtime_s') else None
                row = BenchmarkRecord(
                    record_id=record_id,
                    method=name,
                    reference_latitude=ref_lat,
                    reference_longitude=ref_lon,
                    latitude=lat,
                    longitude=lon,
                    error_m=self.haversine_m(ref_lat, ref_lon, lat, lon),
                    runtime_s=runtime,
                )
                results.append(row)
                record_results.append(row)

            if not record_results:
                skipped.append((index, 'Nessun metodo con coordinate valide'))
                continue
            best_error = min(r.error_m for r in record_results)
            winners = sorted(r.method for r in record_results if abs(r.error_m - best_error) < 1e-9)
            winner_rows.append({
                'record_id': record_id,
                'winner': ' = '.join(winners),
                'best_error_m': best_error,
                'methods_available': len(record_results),
            })

        return results, skipped, winner_rows

    @classmethod
    def _stats(cls, records):
        errors = [r.error_m for r in records if r.error_m is not None and math.isfinite(r.error_m)]
        runtimes = [r.runtime_s for r in records if r.runtime_s is not None and math.isfinite(r.runtime_s)]
        if not errors:
            return {}
        n = len(errors)
        mean = sum(errors) / n
        data = {
            'n': n,
            'mae_m': mean,
            'median_m': median(errors),
            'rmse_m': math.sqrt(sum(v * v for v in errors) / n),
            'min_m': min(errors),
            'max_m': max(errors),
        }
        for threshold in cls.THRESHOLDS_M:
            data[f'within_{threshold}_pct'] = 100.0 * sum(v <= threshold for v in errors) / n
        if runtimes:
            data['runtime_n'] = len(runtimes)
            data['mean_runtime_s'] = sum(runtimes) / len(runtimes)
            data['median_runtime_s'] = median(runtimes)
        return data

    def summarize(self, results, winner_rows, skipped_count=0):
        by_method = {}
        for result in results:
            by_method.setdefault(result.method, []).append(result)
        method_stats = {name: self._stats(records) for name, records in by_method.items()}
        ordered = sorted(method_stats, key=lambda name: (method_stats[name].get('mae_m', float('inf')), name.lower()))

        wins = {name: 0.0 for name in method_stats}
        comparable_records = 0
        for winner_row in winner_rows:
            names = [x.strip() for x in winner_row['winner'].split(' = ') if x.strip()]
            if not names:
                continue
            comparable_records += 1
            share = 1.0 / len(names)
            for name in names:
                wins[name] = wins.get(name, 0.0) + share
        for name, stats in method_stats.items():
            stats['wins'] = wins.get(name, 0.0)
            stats['win_pct'] = (100.0 * wins.get(name, 0.0) / comparable_records) if comparable_records else None

        return {
            'records_compared': len(winner_rows),
            'records_skipped': int(skipped_count),
            'methods': method_stats,
            'ranking_by_mae': ordered,
            'best_method_by_mae': ordered[0] if ordered else None,
            'comparable_records': comparable_records,
        }

    @staticmethod
    def export_long_csv(path, results):
        fields = list(BenchmarkRecord.__dataclass_fields__.keys())
        with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in results:
                writer.writerow(asdict(row))

    @staticmethod
    def export_html(path, summary, results, winner_rows, source_name=''):
        def fmt(value, digits=1, suffix=''):
            if value is None:
                return '—'
            return f'{value:.{digits}f}{suffix}'

        methods = summary.get('methods') or {}
        ranking = summary.get('ranking_by_mae') or []
        lines = [
            '<!doctype html><html><head><meta charset="utf-8">',
            '<title>GeoLichen Benchmark Report</title>',
            '<style>body{font-family:Arial,sans-serif;margin:28px;color:#222}table{border-collapse:collapse;width:100%;margin:12px 0 24px}th,td{border:1px solid #aaa;padding:6px;text-align:left}th{background:#eee}.num{text-align:right}.best{font-weight:bold;background:#eef7ee}</style>',
            '</head><body>',
            '<h1>GeoLichen — Benchmark Report</h1>',
            f'<p><b>Dataset:</b> {html.escape(os.path.basename(source_name)) if source_name else "—"}</p>',
            f'<p><b>Record confrontati:</b> {summary.get("records_compared", 0)} &nbsp; <b>Scartati:</b> {summary.get("records_skipped", 0)}</p>',
            '<p>Il report confronta coordinate già prodotte dai diversi metodi rispetto allo stesso gold standard. Non richiama né simula software esterni.</p>',
            '<h2>Classifica complessiva</h2>',
            '<table><tr><th>Posizione</th><th>Metodo</th><th>N</th><th>MAE (m)</th><th>Mediana (m)</th><th>RMSE (m)</th><th>≤100 m</th><th>≤500 m</th><th>Vittorie</th><th>Tempo medio (s)</th></tr>',
        ]
        for pos, name in enumerate(ranking, start=1):
            s = methods[name]
            cls = ' class="best"' if pos == 1 else ''
            lines.append(
                f'<tr{cls}><td>{pos}</td><td>{html.escape(name)}</td><td class="num">{s.get("n", 0)}</td>'
                f'<td class="num">{fmt(s.get("mae_m"))}</td><td class="num">{fmt(s.get("median_m"))}</td>'
                f'<td class="num">{fmt(s.get("rmse_m"))}</td><td class="num">{fmt(s.get("within_100_pct"),1,"%")}</td>'
                f'<td class="num">{fmt(s.get("within_500_pct"),1,"%")}</td><td class="num">{fmt(s.get("win_pct"),1,"%")}</td>'
                f'<td class="num">{fmt(s.get("mean_runtime_s"),2)}</td></tr>'
            )
        lines.append('</table>')

        lines.append('<h2>Vincitore per record</h2><table><tr><th>ID</th><th>Metodo migliore</th><th>Errore migliore (m)</th><th>Metodi disponibili</th></tr>')
        for row in winner_rows:
            lines.append(f'<tr><td>{html.escape(str(row["record_id"]))}</td><td>{html.escape(row["winner"])}</td><td class="num">{fmt(row["best_error_m"])}</td><td class="num">{row["methods_available"]}</td></tr>')
        lines.append('</table>')

        lines.append('<h2>Risultati completi</h2><table><tr><th>ID</th><th>Metodo</th><th>Errore (m)</th><th>Tempo (s)</th></tr>')
        for row in results:
            lines.append(f'<tr><td>{html.escape(row.record_id)}</td><td>{html.escape(row.method)}</td><td class="num">{fmt(row.error_m)}</td><td class="num">{fmt(row.runtime_s,2)}</td></tr>')
        lines.append('</table><p><i>Fase 12.2: Benchmark Framework indipendente dal motore ecologico.</i></p></body></html>')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines))
