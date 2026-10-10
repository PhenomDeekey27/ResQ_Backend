import httpx
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

SERPAPI_BASE_URL = "https://serpapi.com/search.json"

# Fields to extract from SerpApi Google Maps results
RESULT_FIELDS = [
    "title",
    "address",
    "phone",
    "gps_coordinates",
    "rating",
    "type",
]


class SerpApiError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def search_google_maps(
    query: str,
    latitude: float,
    longitude: float,
) -> list:
    """
    Search Google Maps via SerpApi for nearby places.

    Args:
        query: Search query string (e.g., "hospital", "emergency room", "blood bank")
        latitude: Center latitude
        longitude: Center longitude

    Returns:
        List of normalized place results

    Raises:
        SerpApiError: On API errors, timeouts, or rate limits
    """
    params = {
        "engine": "google_maps",
        "q": query,
        "ll": f"@{latitude},{longitude},14z",
        "type": "search",
        "api_key": settings.serpapi_api_key,
    }

    timeout = httpx.Timeout(settings.serpapi_timeout, connect=5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(SERPAPI_BASE_URL, params=params)
    except httpx.TimeoutException:
        logger.error("SerpApi request timed out")
        raise SerpApiError("Upstream request timed out", status_code=504)
    except httpx.RequestError as e:
        # str(e) for httpx request errors embeds the full request URL, which
        # carries the api_key query parameter. Log only the exception type so a
        # crash report or log stream can never leak the SerpApi key.
        logger.error(f"SerpApi request failed: {type(e).__name__}")
        raise SerpApiError("Upstream request failed", status_code=502)

    if response.status_code == 429:
        logger.warning("SerpApi rate limit exceeded")
        raise SerpApiError("Rate limit exceeded", status_code=503)

    if response.status_code >= 500:
        logger.error(f"SerpApi server error: {response.status_code}")
        raise SerpApiError("Upstream server error", status_code=502)

    if response.status_code != 200:
        logger.error(f"SerpApi error: {response.status_code} - {response.text}")
        raise SerpApiError(f"Upstream error: {response.status_code}", status_code=502)

    try:
        data = response.json()
    except ValueError:
        logger.error("SerpApi returned invalid JSON")
        raise SerpApiError("Invalid upstream response", status_code=502)

    if "error" in data:
        logger.error(f"SerpApi error: {data['error']}")
        raise SerpApiError(data["error"], status_code=502)

    return _normalize_results(data.get("local_results", []))


def _normalize_results(raw_results: list) -> list:
    """Normalize SerpApi Google Maps results to our resource format."""
    normalized = []

    for result in raw_results:
        try:
            coords = result.get("gps_coordinates")
            coordinates = None
            if coords and "latitude" in coords and "longitude" in coords:
                coordinates = {
                    "latitude": float(coords["latitude"]),
                    "longitude": float(coords["longitude"]),
                }

            resource = {
                "name": result.get("title", "Unknown"),
                "address": result.get("address"),
                "phone": result.get("phone"),
                "coordinates": coordinates,
                "rating": result.get("rating"),
            }
            normalized.append(resource)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to normalize result: {e}")
            continue

    return normalized


async def search_hospitals(latitude: float, longitude: float) -> list:
    """Search for hospitals and emergency care facilities."""
    results = []

    # Search for hospitals
    hospital_results = await search_google_maps(
        query="hospital",
        latitude=latitude,
        longitude=longitude,
    )
    for r in hospital_results:
        r["type"] = "hospital"
    results.extend(hospital_results)

    # Search for emergency rooms / emergency care
    er_results = await search_google_maps(
        query="emergency room",
        latitude=latitude,
        longitude=longitude,
    )
    for r in er_results:
        r["type"] = "emergency_care"
    results.extend(er_results)

    return results


async def search_blood_banks(latitude: float, longitude: float) -> list:
    """Search for blood banks."""
    results = await search_google_maps(
        query="blood bank",
        latitude=latitude,
        longitude=longitude,
    )
    for r in results:
        r["type"] = "blood_bank"
    return results


def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate straight-line distance between two coordinates in kilometers (Haversine formula)."""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371.0  # Earth radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c