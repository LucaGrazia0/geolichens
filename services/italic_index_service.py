import json
import os
import re


class ItalicIndexService:
    """Indice locale ITALIC costruito dalle API ufficiali."""

    def __init__(self, index_path=None):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.index_path = index_path or os.path.join(base_dir, "data", "italic_index.json")
        self._index = None

    def _load(self):
        if self._index is not None:
            return self._index
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._index = data if isinstance(data, dict) else {}
        except Exception:
            self._index = {}
        return self._index

    def normalize_key(self, name):
        name = str(name or "").strip()
        name = re.sub(r"\s+", " ", name)
        name = re.sub(r"\s*\([^)]*\)", " ", name).strip()
        name = re.sub(r"\b(et\s+auct\.|auct\.|p\.p\.|s\.l\.|s\.str\.)\b", " ", name, flags=re.I)
        name = re.sub(r"\s+", " ", name).strip(" ,;.")
        return name.lower()

    def base_binomial_key(self, name):
        key = self.normalize_key(name)
        toks = key.split()
        return " ".join(toks[:2]) if len(toks) >= 2 else key

    def lookup(self, name):
        idx = self._load()
        if not idx:
            return None

        key = self.normalize_key(name)
        base = self.base_binomial_key(name)
        for candidate in [key, base]:
            if candidate and candidate in idx:
                return dict(idx[candidate])

        for _, entry in idx.items():
            if not isinstance(entry, dict):
                continue
            names = [
                entry.get("scientific_name"),
                entry.get("scientific_name_full"),
                entry.get("accepted_name"),
                entry.get("related_accepted_name"),
                entry.get("display_name"),
            ]
            names.extend(entry.get("synonyms") or [])
            for n in names:
                nk = self.normalize_key(n)
                nb = self.base_binomial_key(n)
                if nk in {key, base} or nb in {key, base}:
                    return dict(entry)
        return None

    def preferred_api_identifier(self, entry):
        if not isinstance(entry, dict):
            return None
        return (
            entry.get("taxon_id")
            or entry.get("related_taxon_id")
            or entry.get("accepted_name")
            or entry.get("related_accepted_name")
            or entry.get("scientific_name_full")
            or entry.get("scientific_name")
        )

    def taxonpage_url(self, entry):
        if not isinstance(entry, dict):
            return None
        url = entry.get("taxon_url") or entry.get("taxonpage_url")
        if url:
            return str(url)
        num = entry.get("taxonpage_num") or entry.get("num")
        if num in [None, ""]:
            return None
        return f"https://italic.units.it/index.php?procedure=taxonpage&num={num}"
