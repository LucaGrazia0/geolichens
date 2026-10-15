"""Semantic resolver routing for GeoLichen SLGE 2.0."""

from .municipality_resolver import MunicipalityResolver
from .mountain_resolver import MountainResolver
from .area_resolver import AreaResolver
from .point_resolver import PointResolver
from .place_resolver import PlaceResolver


class ResolverRegistry:
    """Route canonical semantic types to specialised resolver families."""

    MUNICIPALITY_TYPES = {"municipality", "admin", "administrative"}
    MOUNTAIN_TYPES = {
        "mountain", "mountain_area", "mountain_group", "massif", "ridge",
        "summit", "summit_peak", "pass", "hill",
    }
    AREA_TYPES = {
        "valley", "forest_area", "hydro", "area", "plateau", "basin", "plain",
    }
    POINT_TYPES = {
        "refuge_malga", "nearby_place", "generic_toponym", "locality", "meadow",
    }

    def __init__(self):
        self._municipality = MunicipalityResolver()
        self._mountain = MountainResolver()
        self._area = AreaResolver()
        self._point = PointResolver()
        self._place = PlaceResolver()

    def get(self, semantic_type):
        key = str(semantic_type or "").strip().lower()
        if key in self.MUNICIPALITY_TYPES:
            return self._municipality
        if key in self.MOUNTAIN_TYPES:
            return self._mountain
        if key in self.AREA_TYPES:
            return self._area
        if key in self.POINT_TYPES:
            return self._point
        if key:
            return self._place
        return None

    def family_for(self, semantic_type):
        resolver = self.get(semantic_type)
        return getattr(resolver, "resolver_family", "") if resolver else ""
