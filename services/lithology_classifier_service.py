class LithologyClassifierService:
    """Classifica descrizioni litologiche in tre macro-gruppi.

    Output standard:
    - calcareo
    - siliceo
    - misto
    - altro
    - unknown

    È pensato sia per il layer geologico sia per il valore del record
    (es. 'Roccia calcarea', 'Tonalite', 'Micascisto', ...).
    """

    CALCAREOUS_TERMS = [
        "calcare", "calcari", "calcarea", "calcarenit", "dolomia", "dolomie",
        "dolomit", "marmo", "marmi", "carbonat", "calcareo", "calcarei",
        "marne calcaree", "marna calc", "calcschist", "calcare saccaroide",
        "calcare silicifero", "calcareo-micacea", "medolo", "esino",
        "calcari dolomitici", "marmi dolomitici", "dolomia principale",
    ]

    SILICEOUS_TERMS = [
        "silice", "silicea", "siliceo", "silicee", "granito", "graniti",
        "tonalite", "gneiss", "micascisto", "micascisti", "scisto", "scisti",
        "quarzite", "quarzit", "quarzifero", "quarzoscisti", "arenaria",
        "arenarie", "arenaria silicea", "porfido", "porfiroid", "pegmatite",
        "rioliti", "andesiti", "daciti", "trachiti", "latiti", "basalto",
        "basalti", "metabasalti", "gabbri", "dioriti", "filladi", "talcoscisto",
        "serpentiniti", "peridotiti", "anfiboliti",
    ]

    MIXED_TERMS = [
        "alternanza", "complesso", "misto", "eterogene", "flysch", "successione",
        "calcari e ", "dolomie e ", "calcari dolomitici", "argille/calcari",
        "conglomerati e arenarie", "ghiaie, blocchi, limi", "manufatti",
    ]

    def classify(self, value: str) -> str:
        if value in [None, ""]:
            return "unknown"

        v = str(value).strip().lower()

        # normalizzazione record-level esplicita
        if any(x in v for x in ["roccia calcarea", "rocce calcaree", "calcarea"]):
            return "calcareo"
        if any(x in v for x in ["roccia silicea", "rocce silicee", "silicea"]):
            return "siliceo"
        if any(x in v for x in ["roccia mista", "rocce miste", "mista"]):
            return "misto"

        is_calc = any(t in v for t in self.CALCAREOUS_TERMS)
        is_sil = any(t in v for t in self.SILICEOUS_TERMS)
        is_mix = any(t in v for t in self.MIXED_TERMS)

        if (is_calc and is_sil) or is_mix:
            return "misto"
        if is_calc:
            return "calcareo"
        if is_sil:
            return "siliceo"
        return "altro"
