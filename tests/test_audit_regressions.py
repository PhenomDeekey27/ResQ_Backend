"""
Regression tests for defects found in the Phase 16 end-to-end audit.

Each test pins one confirmed bug or contract so it cannot silently return:

1. README documented the request field as camelCase ``incidentType`` while the
   real contract (and the Android client) use ``incident_type`` - a client built
   from the README would get 422s on every call.
2. A partial ``coordinates`` mapping (missing or None keys) from the upstream
   normalizer used to be indexed directly, turning one odd result into a
   KeyError 500 for the whole search.
3. httpx request-error logging embedded the full request URL - including the
   SerpApi ``api_key`` query parameter - into server logs.
4. CORS advertised ``allow_origins=["*"]`` together with
   ``allow_credentials=True``, a combination browsers reject and that signals a
   credentialed channel this API does not have.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.serpapi import search_google_maps


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


class TestRequestContractMatchesAndroidClient:
    """The wire contract is snake_case; the README used to advertise camelCase."""

    def test_incident_type_snake_case_accepted(self, client, valid_request):
        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_h, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_b:
            mock_h.return_value = []
            mock_b.return_value = []

            response = client.post(
                "/api/emergency-resources/search", json=valid_request
            )
            assert response.status_code == 200

    def test_incident_type_camel_case_rejected(self, client, valid_request):
        """The exact body the old README showed must 422, not be silently ignored."""
        body = {
            "latitude": valid_request["latitude"],
            "longitude": valid_request["longitude"],
            "incidentType": "possible_accident",
        }
        response = client.post("/api/emergency-resources/search", json=body)
        assert response.status_code == 422


class TestPartialCoordinatesNever500:
    """A malformed upstream coords dict must degrade, not crash the search."""

    def test_coordinates_missing_longitude_excluded_gracefully(self, client, valid_request):
        mock_hospital_results = [
            {
                "name": "Hospital Missing Longitude",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332},  # longitude absent
            },
            {
                "name": "Valid Hospital",
                "type": "hospital",
                "coordinates": {"latitude": 11.95, "longitude": 79.55},
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_h, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_b:
            mock_h.return_value = mock_hospital_results
            mock_b.return_value = []

            response = client.post(
                "/api/emergency-resources/search", json=valid_request
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            names = [r["name"] for r in data["resources"]]
            assert "Valid Hospital" in names
            assert "Hospital Missing Longitude" not in names

    def test_coordinates_with_none_values_excluded_gracefully(self, client, valid_request):
        mock_hospital_results = [
            {
                "name": "Hospital With None Coords",
                "type": "hospital",
                "coordinates": {"latitude": None, "longitude": None},
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_h, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_b:
            mock_h.return_value = mock_hospital_results
            mock_b.return_value = []

            response = client.post(
                "/api/emergency-resources/search", json=valid_request
            )
            assert response.status_code == 200
            assert response.json()["status"] == "no_results"

    def test_dedupe_with_partial_coordinates_does_not_crash(self, client, valid_request):
        """The dedupe path indexed coords["latitude"] directly on any truthy dict."""
        mock_hospital_results = [
            {
                "name": "Shared Name",
                "type": "hospital",
                "coordinates": {"latitude": 11.9332},  # partial dict, same name below
            },
            {
                "name": "shared name",
                "type": "emergency_care",
                "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            },
        ]

        with patch("app.api.routes.search_hospitals", new_callable=AsyncMock) as mock_h, \
             patch("app.api.routes.search_blood_banks", new_callable=AsyncMock) as mock_b:
            mock_h.return_value = mock_hospital_results
            mock_b.return_value = []

            response = client.post(
                "/api/emergency-resources/search", json=valid_request
            )
            assert response.status_code == 200


class TestSerpApiKeyNeverLogged:
    """The api_key rides in the request URL; httpx exception text embeds it."""

    FAKE_KEY = "unit-test-key-must-not-appear-in-logs"

    @pytest.mark.asyncio
    async def test_request_error_log_excludes_api_key(self, caplog):
        request = httpx.Request(
            "GET",
            f"https://serpapi.com/search.json?api_key={self.FAKE_KEY}&q=hospital",
        )
        error = httpx.ConnectError("All connection attempts failed", request=request)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = error

            with caplog.at_level(logging.ERROR, logger="app.services.serpapi"):
                with pytest.raises(Exception):
                    await search_google_maps(
                        query="hospital",
                        latitude=11.9332,
                        longitude=79.5241,
                    )

        assert self.FAKE_KEY not in caplog.text, (
            "SerpApi key leaked into logs via an httpx exception message"
        )


class TestCorsDoesNotAdvertiseCredentialsWithWildcard:
    """ACAO:* + Allow-Credentials:true is rejected by browsers and meaningless here."""

    def test_preflight_returns_wildcard_without_credentials(self, client):
        response = client.options(
            "/api/emergency-resources/search",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "*"
        assert response.headers.get("access-control-allow-credentials") != "true"
