# -*- coding: utf-8 -*-
"""GeoLichen Knowledge Base loader.

Carica dizionari JSON da /knowledge. Se i file non sono presenti o hanno errori,
il plugin continua a funzionare usando fallback interni.
"""

import json
from pathlib import Path


class GeoLichenKnowledgeBase:
    def __init__(self, base_path=None):
        if base_path is None:
            base_path = Path(__file__).resolve().parent.parent / "knowledge"
        self.base_path = Path(base_path)
        self._cache = {}

    def load(self, name, default=None):
        if name in self._cache:
            return self._cache[name]
        default = default if default is not None else {}
        path = self.base_path / f"{name}.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = default
        self._cache[name] = data
        return data

    def soil_ph(self):
        return self.load("soil_ph", default={})


    def load_many(self, names):
        out = []
        for name in names:
            out.append(self.load(name, default={}))
        return out

    def combined_terms(self, names, key):
        """Unisce dizionari multipli della knowledge base."""
        combined = {}
        for data in self.load_many(names):
            group = data.get(key) or {}
            combined.update(group)
        return combined

    def locality_aliases(self):
        data = self.load("toponyms_valcamonica", default={})
        aliases = {}
        for canonical, obj in (data.get("localities") or {}).items():
            aliases[str(canonical).lower()] = canonical
            for a in obj.get("aliases") or []:
                aliases[str(a).lower()] = canonical
        return aliases

    def observed_substrate_terms(self):
        data = self.load("substrates_valcamonica", default={})
        return data.get("terms") or {}


    def aliases_for(self, dict_name, group_key):
        data = self.load(dict_name, default={})
        group = data.get(group_key) or {}
        aliases = {}
        for canonical, obj in group.items():
            aliases[canonical.lower()] = canonical
            for a in obj.get("aliases") or []:
                aliases[str(a).lower()] = canonical
        return aliases
