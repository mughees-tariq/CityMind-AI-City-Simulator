from enum import Enum


class LocationType(Enum):
    EMPTY = "Empty"
    RESIDENTIAL = "Residential"
    HOSPITAL = "Hospital"
    SCHOOL = "School"
    INDUSTRIAL = "Industrial"
    POWER_PLANT = "Power Plant"
    AMBULANCE_DEPOT = "Ambulance Depot"


class RiskLevel(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


locationLetter = {
    LocationType.EMPTY: "",
    LocationType.RESIDENTIAL: "R",
    LocationType.HOSPITAL: "H",
    LocationType.SCHOOL: "S",
    LocationType.INDUSTRIAL: "I",
    LocationType.POWER_PLANT: "P",
    LocationType.AMBULANCE_DEPOT: "D",
}

locationColor = {
    LocationType.EMPTY: "#e2e8f0",
    LocationType.RESIDENTIAL: "#16a34a",
    LocationType.HOSPITAL: "#2563eb",
    LocationType.SCHOOL: "#ca8a04",
    LocationType.INDUSTRIAL: "#ea580c",
    LocationType.POWER_PLANT: "#9333ea",
    LocationType.AMBULANCE_DEPOT: "#e11d48",
}

riskValue = {
    RiskLevel.LOW: 0.10,
    RiskLevel.MEDIUM: 0.50,
    RiskLevel.HIGH: 0.90,
}