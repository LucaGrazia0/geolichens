#!/usr/bin/env python3
"""Costruisce data/italic_index.json usando le API ufficiali ITALIC v2.

Uso:
    python tools/build_italic_index.py --delay 1.25 --merge

Test:
    python tools/build_italic_index.py --delay 1.25 --limit 100 --merge
"""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE_API = "https://italic.units.it/api/v2"
USER_AGENT = "GeoLichen/ITALIC-api-index-builder"


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def normalize_key(name):
    name = str(name or "").strip()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s*\([^)]*\)", " ", name).strip()
    name = re.sub(r"\b(et\s+auct\.|auct\.|p\.p\.|s\.l\.|s\.str\.)\b", " ", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ,;.")
    return name.lower()


def base_binomial_key(name):
    key = normalize_key(name)
    toks = key.split()
    return " ".join(toks[:2]) if len(toks) >= 2 else key


def extract_checklist(data):
    if isinstance(data, dict):
        for key in ["checklist", "data", "taxa", "records"]:
            val = data.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if x]
        for val in data.values():
            if isinstance(val, list):
                return [str(x) for x in val if x]
    if isinstance(data, list):
        return [str(x) for x in data if x]
    return []


def as_entry_from_name_usage(name, usage):
    usage = usage if isinstance(usage, dict) else {}
    accepted = (
        usage.get("related_accepted_name")
        or usage.get("accepted_name")
        or usage.get("scientific_name_full")
        or usage.get("scientific_name")
        or name
    )
    return {
        "scientific_name": usage.get("scientific_name") or base_binomial_key(accepted),
        "scientific_name_full": usage.get("scientific_name_full") or accepted,
        "accepted_name": accepted,
        "display_name": accepted,
        "authorship": usage.get("authorship"),
        "rank": usage.get("rank"),
        "status": usage.get("status"),
        "scientific_name_id": usage.get("scientific_name_id"),
        "index_fungorum_id": usage.get("index_fungorum_id"),
        "related_accepted_name_id": usage.get("related_accepted_name_id"),
        "related_accepted_name": usage.get("related_accepted_name"),
        "taxon_id": usage.get("related_taxon_id") or usage.get("taxon_id"),
        "related_taxon_id": usage.get("related_taxon_id"),
        "source": "ITALIC_API_v2_checklist_name_usage",
        "synonyms": [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.25)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args()

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_path = args.output or os.path.join(base_dir, "data", "italic_index.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    index = {}
    if args.merge and os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, dict):
                index.update(old)
        except Exception:
            pass

    taxa = extract_checklist(fetch_json(BASE_API + "/checklist/"))
    if args.limit:
        taxa = taxa[:args.limit]
    print(f"Checklist taxa: {len(taxa)}")

    for i, name in enumerate(taxa, start=1):
        url = BASE_API + "/name-usage/" + urllib.parse.quote(name, safe="")
        try:
            usage = fetch_json(url)
            entry = as_entry_from_name_usage(name, usage)
            key = base_binomial_key(entry.get("accepted_name") or name)
            original_key = base_binomial_key(name)
            if key:
                index[key] = entry
            if original_key and original_key != key:
                alias = dict(entry)
                alias["synonyms"] = list(dict.fromkeys((alias.get("synonyms") or []) + [name]))
                index[original_key] = alias
            print(f"[{i}/{len(taxa)}] OK {name} -> {entry.get('accepted_name')} taxon_id={entry.get('taxon_id')}")
        except Exception as exc:
            key = base_binomial_key(name)
            if key:
                index[key] = {
                    "scientific_name": key,
                    "accepted_name": name,
                    "display_name": name,
                    "source": "ITALIC_API_v2_checklist_only",
                    "error": str(exc),
                    "synonyms": [],
                }
            print(f"[{i}/{len(taxa)}] ERR {name}: {exc}")

        if i % 25 == 0:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            print(f"[SAVE] {len(index)} entries")

        if args.delay > 0:
            time.sleep(args.delay)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Done. Entries: {len(index)}")
    print(out_path)


if __name__ == "__main__":
    main()
