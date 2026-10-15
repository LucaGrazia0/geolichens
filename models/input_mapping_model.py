from dataclasses import dataclass
from typing import Optional


@dataclass
class InputMappingModel:
    record_id: Optional[str] = None
    municipality: Optional[str] = None
    locality: Optional[str] = None
    scientific_name: Optional[str] = None
    substrate: Optional[str] = None
    rock_type: Optional[str] = None
    tree_type: Optional[str] = None
    elevation: Optional[str] = None
    notes: Optional[str] = None

    def is_valid(self) -> bool:
        return bool(self.municipality or self.locality) and bool(self.scientific_name)

    def to_dict(self):
        return self.__dict__.copy()
