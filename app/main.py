import logging

from fastapi import FastAPI

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
