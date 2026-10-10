# ResQ Emergency Safety Backend

A FastAPI backend for the ResQ emergency-safety Android app providing emergency resource discovery via Google Maps (SerpApi).

## Features

- `GET /health` - Health check endpoint
- `POST /api/emergency-resources/search` - Search for nearby emergency resources (hospitals, blood banks)

## Tech Stack

- Python 3.11+
- FastAPI
- Pydantic v2
- httpx
- pytest

## Quick Start

### 1. Install Dependencies

```bash
cd F:\ResQ_Backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
copy .env.example .env
```

Edit `.env` and add your SerpApi key:
```
SERPAPI_API_KEY=your_actual_key_here
```

Get a key from [SerpApi](https://serpapi.com/).

### 3. Run the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On Render (and similar hosts) the `Procfile` starts the server and honours the
host-provided `PORT` environment variable, falling back to `8000` locally.

### 4. Access API Docs

Open http://localhost:8000/docs in your browser for interactive Swagger UI.

## API Endpoints

### Health Check

```
GET /health
```

Response:
```json
{"status": "healthy"}
```

### Search Emergency Resources

```
POST /api/emergency-resources/search
```

Request body:
```json
{
  "latitude": 11.9332,
  "longitude": 79.5241,
  "incident_type": "possible_accident"
}
```

> **Field name:** the request field is `incident_type` (snake_case), matching
> the Android client. A camelCase `incidentType` key is rejected with `422`.

Response:
```json
{
  "status": "success",
  "resources": [
    {
      "name": "Apollo Hospital",
      "type": "hospital",
      "address": "123 Main St, City",
      "phone": "+91-XXXXXXXXXX",
      "coordinates": {"latitude": 11.9332, "longitude": 79.5241},
      "rating": 4.5,
      "source": "Google Maps",
      "distance_km": 2.3
    }
  ],
  "searched_at": "2026-10-09T10:00:00Z"
}
```

## Running Tests

```bash
pytest -v
```

Or with coverage:
```bash
pytest --cov=app --cov-report=term-missing
```

## Project Structure

```
ResQ_Backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings/configuration
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py       # Request Pydantic models
│   │   └── response.py      # Response Pydantic models
│   ├── services/
│   │   ├── __init__.py
│   │   └── serpapi.py       # SerpApi client
│   └── api/
│       ├── __init__.py
│       └── routes.py        # API route handlers
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures
│   ├── test_health.py
│   └── test_search.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Error Handling

The API returns structured error responses:

```json
{
  "detail": "Invalid coordinates: latitude must be between -90 and 90"
}
```

Common HTTP status codes:
- `200` - Success
- `400` - Invalid request (validation error)
- `422` - Unprocessable entity
- `502` - Upstream API error
- `503` - Service unavailable (timeout/rate limit)
- `504` - Gateway timeout