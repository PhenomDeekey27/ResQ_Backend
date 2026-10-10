import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.models import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ResQ Emergency Safety Backend")
    yield
    logger.info("Shutting down ResQ Emergency Safety Backend")


app = FastAPI(
    title="ResQ Emergency Safety API",
    description="Backend for ResQ emergency-safety Android app providing emergency resource discovery",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return HealthResponse(status="healthy")


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "ResQ Emergency Safety API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }