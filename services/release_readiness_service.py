import configparser
import json
import os
import py_compile
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse


class ReleaseReadinessService:
    REQUIRED_FILES = (
        "__init__.py",
        "plugin.py",
        "metadata.txt",
        "README.md",
        "LICENSE",
        "THIRD_PARTY.md",
        "gui/main_dock.py",
        "controllers/plugin_controller.py",
        "services/scoring_model.py",
        "services/uncertainty_service.py",
        "services/model_confidence_service.py",
        "services/solution_stability_service.py",
        "services/validation_service.py",
        "services/benchmark_service.py",
        "services/interactive_validation_service.py",
    )

    def __init__(self, plugin_dir):
        self.plugin_dir = os.path.abspath(plugin_dir)

    def _result(self, name, ok, detail, severity="error"):
        return {
            "name": name,
            "ok": bool(ok),
            "detail": str(detail),
            "severity": severity,
        }

    def run(self):
        checks = []
        for rel in self.REQUIRED_FILES:
            path = os.path.join(self.plugin_dir, rel)
            checks.append(self._result(
                f"File richiesto: {rel}", os.path.isfile(path),
                "Presente" if os.path.isfile(path) else "Mancante"
            ))

        metadata_path = os.path.join(self.plugin_dir, "metadata.txt")
        metadata = {}
        if os.path.isfile(metadata_path):
            try:
                parser = configparser.ConfigParser()
                parser.read(metadata_path, encoding="utf-8")
                metadata = dict(parser["general"])
                required_keys = (
                    "name", "description", "version", "qgisminimumversion",
                    "author", "email", "about", "license", "homepage",
                    "repository", "tracker",
                )
                for key in required_keys:
                    value = str(metadata.get(key, "")).strip()
                    checks.append(self._result(
                        f"Metadata: {key}", bool(value), value or "Valore assente"
                    ))
                for key in ("homepage", "repository", "tracker"):
                    value = str(metadata.get(key, "")).strip()
                    parsed = urlparse(value)
                    checks.append(self._result(
                        f"URL metadata: {key}",
                        parsed.scheme in {"http", "https"} and bool(parsed.netloc),
                        value or "Inserire il link pubblico verificato",
                    ))
            except Exception as exc:
                checks.append(self._result("Lettura metadata", False, repr(exc)))

        py_files = []
        for root, dirs, files in os.walk(self.plugin_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "dist", "build"}]
            for name in files:
                if name.endswith(".py"):
                    py_files.append(os.path.join(root, name))
        compile_errors = []
        with tempfile.TemporaryDirectory(prefix="geolichen_compile_") as tmpdir:
            for idx, path in enumerate(py_files):
                try:
                    cfile = os.path.join(tmpdir, f"module_{idx}.pyc")
                    py_compile.compile(path, cfile=cfile, doraise=True)
                except Exception as exc:
                    compile_errors.append(f"{os.path.relpath(path, self.plugin_dir)}: {exc}")
        checks.append(self._result(
            "Compilazione Python",
            not compile_errors,
            f"{len(py_files)} file compilati" if not compile_errors else " | ".join(compile_errors[:8])
        ))

        unwanted = []
        for root, dirs, files in os.walk(self.plugin_dir):
            for name in files:
                if name in {".DS_Store", ".Rhistory"} or name.endswith((".pyc", ".pyo")):
                    unwanted.append(os.path.relpath(os.path.join(root, name), self.plugin_dir))
        checks.append(self._result(
            "Pulizia pacchetto",
            not unwanted,
            "Nessun file temporaneo" if not unwanted else f"Da rimuovere: {', '.join(unwanted[:12])}",
            severity="warning",
        ))

        passed = sum(1 for c in checks if c["ok"])
        blocking = [c for c in checks if not c["ok"] and c["severity"] == "error"]
        warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plugin_dir": self.plugin_dir,
            "metadata": metadata,
            "checks": checks,
            "passed": passed,
            "total": len(checks),
            "blocking_failures": len(blocking),
            "warnings": len(warnings),
            "ready": not blocking,
        }

    @staticmethod
    def export_json(report, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
