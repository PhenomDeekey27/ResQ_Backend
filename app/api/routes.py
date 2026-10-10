import logging
from fastapi import APIRouter, HTTPException, status
from app.models import SearchRequest, SearchResponse, Resource, Coordinates
from app.services import (
    search_hospitals,
    search_blood_banks,
    calculate_distance_km,
    SerpApiError,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emergency-resources", tags=["Emergency Resources"])


def _has_valid_coordinates(coords) -> bool:
    """
    True only for a coordinates mapping that carries both numeric keys.

    Upstream normalizers usually guarantee this, but a partial dict (missing
    longitude, None values) used to be indexed directly and turned one odd
    result into a KeyError 500 for the whole search.
    """
    return (
        isinstance(coords, dict)
        and "latitude" in coords
        and "longitude" in coords
        and coords["latitude"] is not None
        and coords["longitude"] is not None
    )


def _deduplicate_resources(resources: list) -> list:
    """
    Deduplicate resources that appear in both hospital and emergency_care searches.
    
    Matching criteria (all must match for a reliable match):
    - Same name (case-insensitive)
    - Same coordinates (within ~100m tolerance)
    
    Does NOT merge unrelated facilities based only on similar names.
    """
    if not resources:
        return []
    
    seen = []
    deduplicated = []
    
    for resource in resources:
        coords = resource.get("coordinates")
        name = resource.get("name", "").strip().lower()
        
        # Try to find a match
        is_duplicate = False
        for existing in seen:
            existing_coords = existing.get("coordinates")
            existing_name = existing.get("name", "").strip().lower()
            
            # Check name match (case-insensitive)
            if name != existing_name or not name:
                continue
            
            # Check coordinate match (within ~100m = 0.1 km)
            if _has_valid_coordinates(coords) and _has_valid_coordinates(existing_coords):
                distance = calculate_distance_km(
                    coords["latitude"], coords["longitude"],
                    existing_coords["latitude"], existing_coords["longitude"]
                )
                if distance <= 0.1:  # Within 100 meters
                    is_duplicate = True
                    break
            # If both have no coordinates, don't deduplicate on name alone
            # (could be different facilities with same name)
        
        if not is_duplicate:
            seen.append(resource)
            deduplicated.append(resource)
    
    return deduplicated


@router.get("/health", response_model=SearchResponse, include_in_schema=False)
async def health_check():
    return SearchResponse(status="success", resources=[])


@router.post("/search", response_model=SearchResponse)
async def search_emergency_resources(request: SearchRequest) -> SearchResponse:
    """
    Search for nearby emergency resources (hospitals, emergency care, blood banks).

    Returns normalized resource objects with available fields.
    Distance is calculated as approximate straight-line distance when coordinates are available.
    Results are filtered to a configurable radius (default 50 km), sorted by distance nearest first,
    and deduplicated across search types.
    """
    lat = request.latitude
    lon = request.longitude
    radius_km = settings.search_radius_km

    try:
        # Search hospitals and emergency care first
        hospital_results = await search_hospitals(lat, lon)

        # Search blood banks as separate category
        blood_bank_results = await search_blood_banks(lat, lon)

    except SerpApiError as e:
        logger.error(f"SerpApi error: {e.message}")
        raise HTTPException(
            status_code=e.status_code or status.HTTP_502_BAD_GATEWAY,
            detail=e.message,
        )

    all_results = hospital_results + blood_bank_results

    if not all_results:
        return SearchResponse(status="no_results", resources=[])

    # Deduplicate results from hospital and emergency_care searches
    all_results = _deduplicate_resources(all_results)

    resources = []
    for result in all_results:
        coords = result.get("coordinates")
        distance = None

        if _has_valid_coordinates(coords):
            distance = calculate_distance_km(
                lat, lon, coords["latitude"], coords["longitude"]
            )

        # Only include resources within the configured radius
        # Exclude resources without valid coordinates (distance cannot be established)
        if distance is not None and distance <= radius_km:
            resource = Resource(
                name=result.get("name", "Unknown"),
                type=result.get("type", "hospital"),
                address=result.get("address"),
                phone=result.get("phone"),
                coordinates=Coordinates(**coords) if _has_valid_coordinates(coords) else None,
                rating=result.get("rating"),
                distance_km=round(distance, 2),
            )
            resources.append(resource)

    # Sort by distance ascending (nearest first)
    resources.sort(key=lambda r: r.distance_km if r.distance_km is not None else float('inf'))

    if not resources:
        return SearchResponse(status="no_results", resources=[])

    return SearchResponse(status="success", resources=resources)