from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LocalityReference:
    ref_type: str
    raw_text: str
    normalized_name: str
    relation: Optional[str] = None
    confidence: float = 0.5


@dataclass
class LocalityParseResultModel:
    original_text: str
    cleaned_text: str
    references: List[LocalityReference] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def get_first_by_type(self, ref_type: str) -> Optional[LocalityReference]:
        for ref in self.references:
            if ref.ref_type == ref_type:
                return ref
        return None

    def best_references(self) -> List[LocalityReference]:
        return sorted(self.references, key=lambda r: r.confidence, reverse=True)
