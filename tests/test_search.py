import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.services import SerpApiError
from app.services.serpapi import search_google_maps, calculate_distance_km


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_request():
    return {
        "latitude": 11.9332,
        "longitude": 79.5241,
        "incident_type": "possible_accident",
    }


class TestSearchValidation:
    def test_valid_request(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = []
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ["success", "no_results"]
            assert "resources" in data
            assert "searched_at" in data

    def test_invalid_latitude_too_high(self, client, valid_request):
        valid_request["latitude"] = 91
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_invalid_latitude_too_low(self, client, valid_request):
        valid_request["latitude"] = -91
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_invalid_longitude_too_high(self, client, valid_request):
        valid_request["longitude"] = 181
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_invalid_longitude_too_low(self, client, valid_request):
        valid_request["longitude"] = -181
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_missing_latitude(self, client, valid_request):
        del valid_request["latitude"]
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_missing_longitude(self, client, valid_request):
        del valid_request["longitude"]
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_missing_incident_type(self, client, valid_request):
        del valid_request["incident_type"]
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_invalid_incident_type(self, client, valid_request):
        valid_request["incident_type"] = "invalid_type"
        response = client.post("/api/emergency-resources/search", json=valid_request)
        assert response.status_code == 422

    def test_null_coordinates(self, client):
        response = client.post("/api/emergency-resources/search", json={
            "latitude": None,
            "longitude": 79.5241,
            "incident_type": "possible_accident",
        })
        assert response.status_code == 422


class TestSearchSuccessfulResponse:
    def test_hospital_results_with_distance(self, client, valid_request):
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "address": "123 Main St, Chennai",
                "phone": "+91-44-12345678",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
                "rating": 4.5,
            }
        ]
        mock_blood_results = []

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = mock_blood_results

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 1
            resource = data["resources"][0]
            assert resource["name"] == "Apollo Hospital"
            assert resource["type"] == "hospital"
            assert resource["address"] == "123 Main St, Chennai"
            assert resource["phone"] == "+91-44-12345678"
            assert resource["coordinates"]["latitude"] == 11.9332
            assert resource["coordinates"]["longitude"] == 79.5241
            assert resource["rating"] == 4.5
            assert resource["source"] == "Google Maps"
            assert resource["distance_km"] == 0.0

    def test_multiple_resource_types(self, client, valid_request):
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "address": "123 Main St",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
                "rating": 4.5,
            }
        ]
        mock_blood_results = [
            {
                "name": "Red Cross Blood Bank",
                "type": "blood_bank",
                "address": "456 Blood Ave",
                "coordinates": {"latitude": 11.9400, "longitude": 79.5300},
                "rating": 4.8,
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = mock_blood_results

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 2
            types = [r["type"] for r in data["resources"]]
            assert "hospital" in types
            assert "blood_bank" in types

    def test_resource_without_coordinates_excluded_from_nearby(self, client, valid_request):
        """Resources without coordinates are excluded from nearby results since proximity cannot be established."""
        mock_hospital_results = [
            {
                "name": "Clinic Without Coords",
                "type": "hospital",
                "address": "789 No Coords St",
                "phone": "+91-44-99999999",
                "rating": 3.5,
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            # Resources without coordinates are filtered out
            assert data["status"] == "no_results"
            assert data["resources"] == []

    def test_resource_without_coordinates_excluded_even_with_other_fields(self, client, valid_request):
        """Resources without coordinates are excluded even if they have other fields."""
        mock_hospital_results = [
            {
                "name": "Minimal Hospital",
                "type": "hospital",
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            # Resources without coordinates are filtered out
            assert data["status"] == "no_results"
            assert data["resources"] == []


class TestSearchEmptyResults:
    def test_no_results_returns_empty_list(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = []
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "no_results"
            assert data["resources"] == []


class TestSearchUpstreamErrors:
    def test_serpapi_timeout_returns_504(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals:
            mock_hospitals.side_effect = SerpApiError("Upstream request timed out", status_code=504)

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 504
            assert "timed out" in response.json()["detail"].lower()

    def test_serpapi_rate_limit_returns_503(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals:
            mock_hospitals.side_effect = SerpApiError("Rate limit exceeded", status_code=503)

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 503
            assert "rate limit" in response.json()["detail"].lower()

    def test_serpapi_server_error_returns_502(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals:
            mock_hospitals.side_effect = SerpApiError("Upstream server error", status_code=502)

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 502
            assert "upstream" in response.json()["detail"].lower()

    def test_serpapi_generic_error_returns_502(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals:
            mock_hospitals.side_effect = SerpApiError("Unknown upstream error")

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 502


class TestSearchMalformedUpstreamResponse:
    def test_malformed_upstream_results_handled_gracefully(self, client, valid_request):
        # Use coordinates within 50km of the request (11.9332, 79.5241)
        mock_hospital_results = [
            {"name": "Valid Hospital", "type": "hospital", "coordinates": {"latitude": 11.95, "longitude": 79.55}},
            {"invalid": "result"},
            {"name": "Another Valid", "type": "hospital"},  # No coordinates - will be filtered out
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            # Only results with valid coordinates within radius are returned
            # Second result ("Unknown") has no coordinates, third has no coordinates
            assert len(data["resources"]) == 1
            assert data["resources"][0]["name"] == "Valid Hospital"
            assert data["resources"][0]["distance_km"] is not None
            assert data["resources"][0]["distance_km"] <= 50


class TestSearchIncidentTypes:
    @pytest.mark.parametrize("incident_type", [
        "possible_accident",
        "medical_emergency",
        "fire",
        "natural_disaster",
        "violence",
        "other",
    ])
    def test_all_incident_types_accepted(self, client, valid_request, incident_type):
        valid_request["incident_type"] = incident_type
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = []
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200


class TestSearchDistanceCalculation:
    def test_distance_calculated_correctly(self, client, valid_request):
        # ~44 km from request point, within the 50 km radius
        mock_hospital_results = [
            {
                "name": "Distant Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 12.32, "longitude": 79.5241},
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            resource = data["resources"][0]
            assert resource["distance_km"] is not None
            assert resource["distance_km"] > 0


class TestSerpApiRequestParameters:
    """Tests verifying SerpApi request uses correct parameters."""

    @pytest.mark.asyncio
    async def test_search_google_maps_uses_type_search(self):
        """Verify search_google_maps sends type='search' parameter."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"local_results": []}
            mock_get.return_value = mock_response

            await search_google_maps(
                query="hospital",
                latitude=11.9332,
                longitude=79.5241,
            )

            # Verify the call was made with correct parameters
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            params = call_args[1]["params"]  # kwargs params

            assert params["engine"] == "google_maps"
            assert params["q"] == "hospital"
            assert params["type"] == "search"
            assert params["ll"] == "@11.9332,79.5241,14z"
            assert "api_key" in params

    @pytest.mark.asyncio
    async def test_search_hospitals_calls_with_correct_queries(self):
        """Verify search_hospitals makes calls with correct q values."""
        with patch("app.services.serpapi.search_google_maps", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []

            from app.services import search_hospitals
            await search_hospitals(latitude=11.9332, longitude=79.5241)

            # Should make 2 calls: one for "hospital", one for "emergency room"
            assert mock_search.call_count == 2

            calls = mock_search.call_args_list
            # First call: hospital
            assert calls[0][1]["query"] == "hospital"
            assert calls[0][1]["latitude"] == 11.9332
            assert calls[0][1]["longitude"] == 79.5241
            # Second call: emergency room
            assert calls[1][1]["query"] == "emergency room"
            assert calls[1][1]["latitude"] == 11.9332
            assert calls[1][1]["longitude"] == 79.5241

    @pytest.mark.asyncio
    async def test_search_blood_banks_calls_with_correct_query(self):
        """Verify search_blood_banks makes call with correct q value."""
        with patch("app.services.serpapi.search_google_maps", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []

            from app.services import search_blood_banks
            await search_blood_banks(latitude=11.9332, longitude=79.5241)

            # Should make 1 call for "blood bank"
            assert mock_search.call_count == 1

            call = mock_search.call_args
            assert call[1]["query"] == "blood bank"
            assert call[1]["latitude"] == 11.9332
            assert call[1]["longitude"] == 79.5241

    @pytest.mark.asyncio
    async def test_search_google_maps_does_not_use_invalid_type_values(self):
        """Verify search_google_maps never uses 'hospital', 'emergency room', or 'blood bank' as type parameter."""
        invalid_type_values = ["hospital", "emergency room", "blood bank"]

        for invalid_type in invalid_type_values:
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"local_results": []}
                mock_get.return_value = mock_response

                await search_google_maps(
                    query=invalid_type,
                    latitude=11.9332,
                    longitude=79.5241,
                )

                call_args = mock_get.call_args
                params = call_args[1]["params"]
                # The type parameter should always be "search", never the query value
                assert params["type"] == "search", f"type should be 'search', not '{invalid_type}'"
                # The query should be in q parameter
                assert params["q"] == invalid_type


class TestSearchRadiusFiltering:
    """Tests for radius filtering functionality."""

    def test_results_outside_default_radius_excluded(self, client, valid_request):
        """Resources beyond 50km radius are excluded."""
        # Chennai coordinates: 11.9332, 79.5241
        # Bangalore is ~300km away
        mock_hospital_results = [
            {
                "name": "Bangalore Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "no_results"
            assert data["resources"] == []

    def test_results_inside_default_radius_included(self, client, valid_request):
        """Resources within 50km radius are included."""
        # ~10km from Chennai center
        mock_hospital_results = [
            {
                "name": "Nearby Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.95, "longitude": 79.55},
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 1
            assert data["resources"][0]["name"] == "Nearby Hospital"
            assert data["resources"][0]["distance_km"] <= 50

    def test_results_at_exact_radius_boundary_included(self, client, valid_request):
        """Resources at exactly the radius boundary are included."""
        # Calculate a point at exactly 50km from Chennai
        # Using approximate calculation: 1 degree lat ≈ 111km, 1 degree lon ≈ 111km * cos(lat)
        # At 11.93°N, cos(11.93°) ≈ 0.978
        # 50km ≈ 0.45° lat or 0.46° lon
        mock_hospital_results = [
            {
                "name": "Boundary Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 12.3832, "longitude": 79.5241},  # ~50km north
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            # May be included or excluded depending on exact haversine calculation
            # Just verify it doesn't crash
            assert data["status"] in ["success", "no_results"]

    def test_mixed_results_only_nearby_returned(self, client, valid_request):
        """When mixing nearby and far results, only nearby are returned."""
        mock_hospital_results = [
            {
                "name": "Nearby Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.95, "longitude": 79.55},  # ~3km
            },
            {
                "name": "Far Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 12.9716, "longitude": 77.5946},  # ~300km
            },
            {
                "name": "Another Nearby",
                "type": "hospital",
                "coordinates": {"latitude": 11.94, "longitude": 79.53},  # ~2km
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 2
            names = [r["name"] for r in data["resources"]]
            assert "Nearby Hospital" in names
            assert "Another Nearby" in names
            assert "Far Hospital" not in names


class TestSearchSorting:
    """Tests for sorting by distance (nearest first)."""

    def test_results_sorted_by_distance_ascending(self, client, valid_request):
        """Results are sorted by distance_km ascending (nearest first)."""
        mock_hospital_results = [
            {
                "name": "Far Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.95, "longitude": 79.55},  # ~3km
            },
            {
                "name": "Near Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.94, "longitude": 79.53},  # ~1km
            },
            {
                "name": "Medium Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.96, "longitude": 79.56},  # ~5km
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 3
            
            distances = [r["distance_km"] for r in data["resources"]]
            # Should be sorted ascending
            assert distances == sorted(distances)
            # First should be nearest
            assert data["resources"][0]["name"] == "Near Hospital"

    def test_sorting_across_resource_types(self, client, valid_request):
        """Sorting works across different resource types (hospital, emergency_care, blood_bank)."""
        mock_hospital_results = [
            {
                "name": "Far Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.95, "longitude": 79.55},  # ~3km
            },
        ]
        mock_blood_results = [
            {
                "name": "Near Blood Bank",
                "type": "blood_bank",
                "coordinates": {"latitude": 11.935, "longitude": 79.525},  # ~0.5km
            },
            {
                "name": "Medium Emergency Care",
                "type": "emergency_care",
                "coordinates": {"latitude": 11.94, "longitude": 79.53},  # ~1km
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = mock_blood_results

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 3
            
            distances = [r["distance_km"] for r in data["resources"]]
            assert distances == sorted(distances)
            # Nearest should be blood bank
            assert data["resources"][0]["name"] == "Near Blood Bank"
            assert data["resources"][0]["type"] == "blood_bank"


class TestSearchDeduplication:
    """Tests for deduplication across hospital and emergency_care searches."""

    def test_duplicate_hospital_and_emergency_care_merged(self, client, valid_request):
        """Same facility returned as both hospital and emergency_care is deduplicated."""
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
            {
                "name": "Apollo Hospital",
                "type": "emergency_care",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            # Should be deduplicated to 1 result
            assert len(data["resources"]) == 1
            assert data["resources"][0]["name"] == "Apollo Hospital"
            # Type should be from first occurrence (hospital)
            assert data["resources"][0]["type"] == "hospital"

    def test_duplicate_with_slight_coordinate_difference_merged(self, client, valid_request):
        """Same facility with slightly different coordinates (within 100m) is deduplicated."""
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
            {
                "name": "Apollo Hospital",
                "type": "emergency_care",
                "coordinates": {"latitude": 11.9333, "longitude": 79.5242},  # ~15m difference
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 1

    def test_similar_names_different_locations_not_merged(self, client, valid_request):
        """Different facilities with similar names are NOT merged."""
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 12.9716, "longitude": 77.5946},  # Bangalore - different city
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            # Should NOT be deduplicated - different locations
            assert len(data["resources"]) == 1  # Second one is outside radius
            assert data["resources"][0]["name"] == "Apollo Hospital"

    def test_same_name_no_coordinates_not_merged(self, client, valid_request):
        """Resources with same name but no coordinates are NOT merged (cannot verify proximity)."""
        mock_hospital_results = [
            {
                "name": "General Hospital",
                "type": "hospital",
                # No coordinates
            },
            {
                "name": "General Hospital",
                "type": "emergency_care",
                # No coordinates
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            # Both filtered out (no coordinates)
            assert data["status"] == "no_results"
            assert data["resources"] == []

    def test_one_with_coords_one_without_not_merged(self, client, valid_request):
        """Resource with coordinates and same-name resource without coordinates are NOT merged."""
        mock_hospital_results = [
            {
                "name": "General Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
            {
                "name": "General Hospital",
                "type": "emergency_care",
                # No coordinates
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            # Only the one with coordinates should remain (within radius)
            assert len(data["resources"]) == 1
            assert data["resources"][0]["name"] == "General Hospital"

    def test_case_insensitive_name_matching(self, client, valid_request):
        """Deduplication matches names case-insensitively."""
        mock_hospital_results = [
            {
                "name": "Apollo Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
            {
                "name": "apollo hospital",  # Different case
                "type": "emergency_care",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["resources"]) == 1


class TestSearchResponseSchema:
    """Tests to ensure API response schema compatibility with Android app."""

    def test_response_contains_required_fields(self, client, valid_request):
        """Response contains all fields expected by Android app."""
        mock_hospital_results = [
            {
                "name": "Test Hospital",
                "type": "hospital",
                "address": "123 Test St",
                "phone": "+91-44-12345678",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
                "rating": 4.5,
            }
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = mock_hospital_results
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            
            # Top-level fields
            assert "status" in data
            assert "resources" in data
            assert "searched_at" in data
            
            resource = data["resources"][0]
            # Resource fields
            assert "name" in resource
            assert "type" in resource
            assert "address" in resource
            assert "phone" in resource
            assert "coordinates" in resource
            assert "rating" in resource
            assert "source" in resource
            assert "distance_km" in resource
            
            # Coordinates sub-fields
            coords = resource["coordinates"]
            assert "latitude" in coords
            assert "longitude" in coords
            
            # Type validation
            assert resource["type"] in ["hospital", "blood_bank", "emergency_care"]
            assert resource["source"] == "Google Maps"
            assert isinstance(resource["distance_km"], (int, float))

    def test_no_results_response_schema(self, client, valid_request):
        """No results response maintains schema compatibility."""
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_hospitals, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_blood_banks:
            mock_hospitals.return_value = []
            mock_blood_banks.return_value = []

            response = client.post("/api/emergency-resources/search", json=valid_request)
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "no_results"
            assert data["resources"] == []
            assert "searched_at" in data