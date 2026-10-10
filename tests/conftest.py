import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_serpapi_hospitals():
    return [
        {
            "name": "Apollo Hospital",
            "type": "hospital",
            "address": "123 Main St, Chennai",
            "phone": "+91-44-12345678",
            "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
            "rating": 4.5,
        },
        {
            "name": "Fortis Emergency Care",
            "type": "emergency_care",
            "address": "456 Emergency Rd, Chennai",
            "phone": "+91-44-87654321",
            "coordinates": {"latitude": 11.9400, "longitude": 79.5300},
            "rating": 4.2,
        },
    ]


@pytest.fixture
def mock_serpapi_blood_banks():
    return [
        {
            "name": "Red Cross Blood Bank",
            "type": "blood_bank",
            "address": "789 Blood Bank Ave, Chennai",
            "phone": "+91-44-11111111",
            "coordinates": {"latitude": 11.9200, "longitude": 79.5100},
            "rating": 4.8,
        }
    ]


@pytest.fixture
def valid_search_request():
    return {
        "latitude": 11.9332,
        "longitude": 79.5241,
        "incident_type": "possible_accident",
    }