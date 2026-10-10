from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    serpapi_api_key: str = Field(..., description="SerpApi API key for Google Maps search")
    serpapi_timeout: int = Field(10, description="Timeout for SerpApi requests in seconds")
    search_radius_km: int = Field(50, description="Default search radius in kilometers for nearby resources")
    log_level: str = Field("INFO", description="Log level")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()