"""Parser conservativo degli offset geografici descritti nel campo Località."""

import re
import unicodedata


class LocalityOffsetParser:
    UNIT_FACTORS = {
        "m": 1.0, "metro": 1.0, "metri": 1.0,
        "km": 1000.0, "chilometro": 1000.0, "chilometri": 1000.0,
        "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    }
    HEADINGS = {
        "n": 0.0, "nord": 0.0,
        "ne": 45.0, "nord-est": 45.0, "nordest": 45.0,
        "e": 90.0, "est": 90.0,
        "se": 135.0, "sud-est": 135.0, "sudest": 135.0,
        "s": 180.0, "sud": 180.0,
        "so": 225.0, "sw": 225.0, "sud-ovest": 225.0, "sudovest": 225.0,
        "o": 270.0, "w": 270.0, "ovest": 270.0,
        "no": 315.0, "nw": 315.0, "nord-ovest": 315.0, "nordovest": 315.0,
    }

    def parse(self, text):
        original = str(text or "").strip()
        normalized = self._normalize(original)
        if not normalized:
            return {}

        measures = list(self._measure_matches(normalized))
        along = bool(re.search(r"\b(?:lungo|seguendo|percorren(?:do|za)|via strada|su sentiero)\b", normalized))

        # Two explicit measures linked to two paths/features.
        if len(measures) >= 2 and len(re.findall(r"\b(?:strada|sentiero|percorso|fiume|torrente|canale|path)\b", normalized)) >= 2:
            return {
                "kind": "two_distinct_paths",
                "distance_a_m": measures[0][0],
                "precision_a_m": measures[0][1],
                "distance_b_m": measures[1][0],
                "precision_b_m": measures[1][1],
                "verbatim": original,
            }

        if along and measures:
            return {
                "kind": "along_path",
                "distance_m": measures[0][0],
                "distance_precision_m": measures[0][1],
                "path_start": "both",
                "verbatim": original,
            }

        directional = []
        for distance, precision, start, end in measures:
            tail = normalized[end:end + 30]
            heading = self._heading_from_text(tail)
            if heading is not None:
                directional.append((distance, precision, heading))

        # Orthogonal offsets require one N/S and one E/W component.
        if len(directional) >= 2:
            north = east = 0.0
            precisions = []
            for distance, precision, heading in directional[:2]:
                dx, dy = self._components(distance, heading)
                east += dx
                north += dy
                precisions.append(precision)
            if abs(north) > 0 and abs(east) > 0:
                return {
                    "kind": "orthogonal_offsets",
                    "north_m": north,
                    "east_m": east,
                    "distance_precision_m": sum(precisions),
                    "verbatim": original,
                }

        if directional:
            distance, precision, heading = directional[0]
            return {
                "kind": "distance_at_heading",
                "distance_m": distance,
                "distance_precision_m": precision,
                "heading_deg": heading,
                "verbatim": original,
            }

        if measures and re.search(r"\b(?:da|di|dal|dalla|distanza|raggio)\b", normalized):
            return {
                "kind": "distance_only",
                "distance_m": measures[0][0],
                "distance_precision_m": measures[0][1],
                "verbatim": original,
            }
        return {}

    def _measure_matches(self, text):
        pattern = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)\s*(km|chilometri?|m|metri?|mi|miles?)(?!\w)")
        for match in pattern.finditer(text):
            value_text = match.group(1).replace(",", ".")
            value = float(value_text)
            unit = match.group(2)
            factor = self.UNIT_FACTORS.get(unit, 1.0)
            yield value * factor, self._precision_m(value_text, factor), match.start(), match.end()

    def _heading_from_text(self, text):
        degree = re.search(r"\b(\d{1,3}(?:[\.,]\d+)?)\s*(?:°|gradi)\b", text)
        if degree:
            return float(degree.group(1).replace(",", ".")) % 360.0
        for token in sorted(self.HEADINGS, key=len, reverse=True):
            if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text):
                return self.HEADINGS[token]
        return None

    @staticmethod
    def _components(distance, heading):
        import math
        rad = math.radians(heading)
        return distance * math.sin(rad), distance * math.cos(rad)

    @staticmethod
    def _precision_m(number_text, factor):
        # Half of the unit represented by the last stated digit.
        decimals = len(number_text.split(".", 1)[1]) if "." in number_text else 0
        return 0.5 * (10 ** (-decimals)) * factor

    @staticmethod
    def _normalize(value):
        text = str(value or "").strip().replace("’", "'")
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", text.casefold()).strip()
