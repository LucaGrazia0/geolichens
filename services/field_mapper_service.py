from ..models.input_mapping_model import InputMappingModel


class FieldMapperService:
    DEFAULT_MAP = {
        "record_id": ["record_id", "id", "occurrenceid", "occurrence_id", "nrecord", "n record"],
        "municipality": ["municipality", "comune", "nome_comune", "comune attuale", "comune_attuale", "provincia/comune", "comune di raccolta", "h", "Comune"],
        "locality": ["locality", "localita", "località", "loc", "place", "descrizione_localita", "descrizione localita", "j", "Località"],
        "scientific_name": ["scientificname", "scientific_name", "species", "taxon", "taxon accepted", "Taxon", "nome nella fonte", "Nome nella fonte", "nome della fonte", "Nome della fonte"],
        "substrate": ["substrato", "substrate", "sub", "s", "Substrato", "suolo (terricoli)"],
        "rock_type": ["roccia", "rock_type", "litologia", "roccia (sassicoli)", "u", "Roccia (sassicoli)", "formazione (sassicoli)"],
        "tree_type": ["albero", "tree", "tree_type", "phorophyte", "forofita (epifiti)", "t", "Forofita (epifiti)"],
        "elevation": ["quota", "elevation", "altitudine", "r", "Quota"],
        "notes": ["note", "notes", "remarks", "note ecologiche", "altre note", "ab", "ai", "Note ecologiche"],
    }

    def suggest_mapping(self, field_names):
        lowered = {f.lower(): f for f in field_names}
        out = InputMappingModel()
        for logical, aliases in self.DEFAULT_MAP.items():
            for alias in aliases:
                if alias.lower() in lowered:
                    setattr(out, logical, lowered[alias.lower()])
                    break
        return out
