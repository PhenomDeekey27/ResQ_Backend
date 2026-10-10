from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime


class Coordinates(BaseModel):
    latitude: float
    longitude: float


class Resource(BaseModel):
    name: str
    type: Literal["hospital", "blood_bank", "emergency_care"]
    address: Optional[str] = None
    phone: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    rating: Optional[float] = None
    source: Literal["Google Maps"] = "Google Maps"
    distance_km: Optional[float] = Field(None, description="Approximate straight-line distance in km")


class SearchResponse(BaseModel):
    status: Literal["success", "no_results"] = "success"
    resources: List[Resource] = []
    searched_at: datetime = Field(default_factory=datetime.utcnow)