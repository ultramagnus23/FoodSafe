"""
FoodSafe India — FastAPI Application Entry Point
Run: uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations
import logging, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api.db import init_pool, close_pool
from api.auth import auth_router
from api.routes.risk import risk_router
from api.routes.user import user_router
from api.routes.disputes import disputes_router, admin_router
from api.other_routes import search_router, fmcg_router, insurance_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("foodsafe.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    logger.info("FoodSafe India API v1.1 started")
    yield
    await close_pool()

app = FastAPI(title="FoodSafe India API", version="1.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","https://foodsafe.in"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    logger.info("%s %s → %d (%dms)", request.method, request.url.path,
                response.status_code, int((time.monotonic()-t0)*1000))
    return response

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    logger.error("Unhandled: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth_router,      prefix="/v1/auth",      tags=["auth"])
app.include_router(risk_router,      prefix="/v1/risk",      tags=["risk"])
app.include_router(user_router,      prefix="/v1/user",      tags=["user"])
app.include_router(search_router,    prefix="/v1/search",    tags=["search"])
app.include_router(fmcg_router,      prefix="/v1/fmcg",      tags=["fmcg"])
app.include_router(insurance_router, prefix="/v1/insurance", tags=["insurance"])
app.include_router(disputes_router,  prefix="/v1/disputes",  tags=["disputes"])
app.include_router(admin_router,     prefix="/v1/admin",     tags=["admin"])

@app.get("/", include_in_schema=False)
async def root():
    return {"service": "FoodSafe India API", "version": "1.1.0", "status": "ok"}
