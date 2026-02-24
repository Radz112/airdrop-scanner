import logging
import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.middleware.apix402 import APIX402BodyUnwrapper
from app.middleware.rate_limit import RateLimitMiddleware
from app.routes.airdrop import router as airdrop_router
from app.services.protocol_db import protocol_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("app")

class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"{request.method} {request.url.path} → {response.status_code} "
            f"({duration_ms:.1f}ms)"
        )
        return response


app = FastAPI(
    title="Airdrop Likelihood / Exposure Scanner API",
    description=(
        "Scan wallets for interactions with tokenless protocols "
        "and score airdrop likelihood on Base and Solana."
    ),
    version="0.1.0",
)

# Middleware (order: last added = outermost = runs first)
app.add_middleware(APIX402BodyUnwrapper)
app.add_middleware(RateLimitMiddleware, requests_per_minute=100)
app.add_middleware(RequestTimingMiddleware)

app.include_router(airdrop_router)


@app.on_event("startup")
async def startup():
    logger.info("Loading protocol database...")
    protocol_db.load()
    logger.info(f"Ready — {protocol_db.count} protocols loaded")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "protocols_loaded": protocol_db.count,
        "supported_chains": settings.supported_chains,
    }
