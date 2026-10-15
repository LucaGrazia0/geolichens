import json
import os
import platform
import time
from datetime import datetime, timezone


class PerformanceService:
    """Registro leggero di prestazioni e diagnostica runtime.

    Non modifica il motore ecologico: osserva solamente durata, stato e
    informazioni di contesto delle operazioni principali.
    """

    def __init__(self, max_records=250):
        self.max_records = int(max_records)
        self.records = []
        self._active = {}

    def start(self, operation, context=None):
        token = f"{operation}:{time.perf_counter_ns()}"
        self._active[token] = {
            "operation": str(operation),
            "started": time.perf_counter(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "context": dict(context or {}),
        }
        return token

    def finish(self, token, status="ok", details=None):
        item = self._active.pop(token, None)
        if item is None:
            return None
        item["duration_s"] = max(0.0, time.perf_counter() - item.pop("started"))
        item["status"] = str(status or "ok")
        item["details"] = dict(details or {})
        self.records.append(item)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        return item

    def clear(self):
        self.records = []
        self._active = {}

    def summary(self):
        grouped = {}
        for record in self.records:
            op = record.get("operation", "unknown")
            grouped.setdefault(op, []).append(record)
        operations = []
        for op, rows in sorted(grouped.items()):
            durations = [float(r.get("duration_s", 0.0)) for r in rows]
            failures = sum(1 for r in rows if r.get("status") != "ok")
            operations.append({
                "operation": op,
                "runs": len(rows),
                "failures": failures,
                "mean_s": sum(durations) / len(durations) if durations else 0.0,
                "min_s": min(durations) if durations else 0.0,
                "max_s": max(durations) if durations else 0.0,
                "last_s": durations[-1] if durations else 0.0,
            })
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_runs": len(self.records),
            "operations": operations,
            "records": list(self.records),
        }

    @staticmethod
    def runtime_environment(qgis_version=None):
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "qgis": str(qgis_version or "non disponibile"),
            "working_directory": os.getcwd(),
        }

    def export_json(self, path, extra=None):
        payload = self.summary()
        if extra:
            payload["environment"] = dict(extra)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
