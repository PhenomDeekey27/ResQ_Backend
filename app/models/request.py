from pydantic import BaseModel, Field, field_validator
from typing import Literal


class SearchRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    incident_type: Literal[
        "possible_accident",
        "medical_emergency",
        "fire",
        "natural_disaster",
        "violence",
        "other"
    ] = Field(..., description="Type of emergency incident")

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def validate_coordinates(cls, v):
        if v is None:
            raise ValueError("Coordinate cannot be null")
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError("Coordinate must be a valid number")


class HealthResponse(BaseModel):
    status: Literal["healthy"] = "healthy"