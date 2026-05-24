from dataclasses import dataclass
from city.constants import LocationType


@dataclass
class CityNode:
    nodeId: int
    row: int
    col: int
    locationType: LocationType = LocationType.EMPTY
    populationDensity: float = 0.0
    riskIndex: float = 0.0
    accessible: bool = True