class SearchAreaService:
    """Gestione ordinata e persistente delle aree di ricerca geocoding.

    La bbox è in ordine:
    xmin, ymin, xmax, ymax
    coordinate WGS84.
    """

    AREAS = {
        "Italia": (6.60, 35.40, 18.60, 47.20),

        # Regioni italiane
        "Abruzzo": (13.00, 41.68, 14.80, 42.95),
        "Basilicata": (15.34, 39.88, 16.87, 41.14),
        "Calabria": (15.63, 37.90, 17.25, 40.15),
        "Campania": (13.75, 39.98, 15.80, 41.55),
        "Emilia-Romagna": (9.18, 43.70, 12.85, 45.15),
        "Friuli Venezia Giulia": (12.30, 45.55, 13.95, 46.65),
        "Lazio": (11.45, 40.78, 14.05, 42.85),
        "Liguria": (7.45, 43.75, 10.10, 44.70),
        "Lombardia": (8.45, 44.70, 11.45, 46.70),
        "Marche": (12.10, 42.68, 13.92, 44.35),
        "Molise": (13.90, 41.35, 15.20, 42.10),
        "Piemonte": (6.60, 44.00, 9.25, 46.50),
        "Puglia": (14.90, 39.75, 18.55, 42.25),
        "Sardegna": (8.10, 38.85, 9.85, 41.35),
        "Sicilia": (11.85, 36.60, 15.75, 38.85),
        "Toscana": (9.65, 42.20, 12.40, 44.55),
        "Trentino-Alto Adige": (10.35, 45.65, 12.50, 47.10),
        "Umbria": (11.85, 42.35, 13.30, 43.65),
        "Valle d'Aosta": (6.80, 45.45, 7.95, 46.15),
        "Veneto": (10.60, 44.75, 13.10, 46.75),

        # Macroaree alpine
        "Alpi Occidentali": (6.50, 43.80, 8.60, 46.40),
        "Alpi Centrali": (8.20, 45.30, 11.30, 47.20),
        "Alpi Orientali": (10.70, 45.30, 13.95, 47.10),

        # Catene alpine principali
        "Alpi Liguri": (7.35, 43.85, 8.35, 44.45),
        "Alpi Marittime": (6.80, 43.95, 7.85, 44.65),
        "Alpi Cozie": (6.60, 44.30, 7.75, 45.20),
        "Alpi Graie": (6.75, 45.05, 8.10, 46.20),
        "Alpi Pennine": (7.30, 45.55, 8.45, 46.50),
        "Alpi Lepontine": (8.10, 45.85, 9.80, 46.70),
        "Alpi Retiche": (9.50, 45.75, 11.40, 47.00),
        "Dolomiti": (11.20, 45.85, 12.70, 46.85),
        "Alpi Carniche": (12.30, 46.20, 13.20, 46.75),
        "Alpi Giulie": (13.00, 45.95, 13.95, 46.65),

        # Appennini
        "Appennino Settentrionale": (8.80, 43.20, 12.40, 45.10),
        "Appennino Centrale": (11.80, 41.60, 14.30, 43.80),
        "Appennino Meridionale": (13.80, 39.60, 16.70, 42.00),
    }

    DEFAULT_AREA = "Lombardia"
    CUSTOM_AREA_NAME = "Personalizzata"

    @classmethod
    def names(cls):
        return list(cls.AREAS.keys()) + [cls.CUSTOM_AREA_NAME]

    @classmethod
    def bbox_for(cls, name, custom_bbox=None):
        if name == cls.CUSTOM_AREA_NAME:
            return cls.parse_bbox(custom_bbox)
        return cls.AREAS.get(name) or cls.AREAS[cls.DEFAULT_AREA]

    @classmethod
    def parse_bbox(cls, value):
        if value in [None, "", [], {}]:
            return None
        try:
            vals = [float(v.strip()) for v in str(value).split(",")]
            if len(vals) != 4:
                return None
            xmin, ymin, xmax, ymax = vals
            if xmin >= xmax or ymin >= ymax:
                return None
            return (xmin, ymin, xmax, ymax)
        except Exception:
            return None

    @classmethod
    def bbox_to_text(cls, bbox):
        if not bbox:
            return ""
        return ",".join(f"{float(v):.5f}".rstrip("0").rstrip(".") for v in bbox)
