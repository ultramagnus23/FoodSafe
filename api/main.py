"""
FoodSafe India — FastAPI Application Entry Point
Run: uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations
import logging, os, threading, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api.db import init_pool, close_pool
from api.auth_utils import SECRET_KEY, ALGORITHM, TIER_LIMITS
import jwt as _jwt
from api.auth import auth_router
from api.routes.risk import risk_router
from api.routes.user import user_router
from api.routes.disputes import disputes_router, admin_router
from api.routes.disease import disease_router
from api.routes.trends import trends_router
from api.routes.compare import compare_router
from api.routes.admin_panel import admin_panel_router
from api.routes.api_keys import api_keys_router
from api.routes.subscriptions import subscriptions_router
from api.routes.reports import reports_router, admin_reports_router
from api.routes.widget import widget_router
from api.routes.research import research_router
from api.routes.rasff import rasff_router
from api.other_routes import search_router, fmcg_router, insurance_router, meta_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("foodsafe.api")

# ------------------------------------------------------------
# Error tracking — opt-in via SENTRY_DSN. A no-op if unset (local dev,
# CI), so this never becomes a hard dependency. sentry-sdk is already in
# requirements.txt/requirements-api.txt; import is deferred into the `if`
# so a missing package in some other environment can't break startup.
# ------------------------------------------------------------
_SENTRY_DSN = os.environ.get("SENTRY_DSN")
if _SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.environ.get("ENVIRONMENT", "development"),
        release=os.environ.get("RENDER_GIT_COMMIT"),
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
    logger.info("Sentry error tracking initialised")
else:
    logger.info("SENTRY_DSN not set — error tracking disabled")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    logger.info("FoodSafe India API v1.1 started")
    yield
    await close_pool()

app = FastAPI(title="FoodSafe India API", version="1.1.0", lifespan=lifespan)

# CORS: local dev origins are always allowed; the deployed Vercel frontend is
# added via FRONTEND_URL (set in Render's env, see render.yaml). Vercel
# preview deploys (*.vercel.app) are matched by regex so PR previews work
# without listing every preview URL by hand.
_default_origins = ["http://localhost:3000", "https://foodsafe.in"]
_frontend_url = os.environ.get("FRONTEND_URL")
if _frontend_url and _frontend_url not in _default_origins:
    _default_origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ------------------------------------------------------------
# Rate limiting (Task 11b) — tiered per-day limits for JWT/anonymous
# requests, reusing TIER_LIMITS already defined for CurrentUser. API-key
# requests are limited separately in api/auth_utils.py using persisted
# api_key_usage counts (survives restarts); this one is in-memory, so it
# resets on deploy and doesn't share state across multiple Render
# instances — a known limitation, same tradeoff already accepted by
# deferring Redis (Task 11a) for this pass.
# ------------------------------------------------------------
UNAUTH_LIMIT_PER_DAY = 20
_RATE_WINDOW_SECONDS = 24 * 3600
_rate_limit_lock = threading.Lock()
_rate_limit_state: dict[str, tuple[float, int]] = {}
_UNLIMITED_PATHS = {"/", "/docs", "/openapi.json", "/redoc"}


def _rate_limit_key_and_cap(request: Request) -> tuple[str, int]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = _jwt.decode(auth[7:], SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("type") == "access":
                tier = payload.get("tier", "consumer_free")
                return f"user:{payload.get('sub')}", TIER_LIMITS.get(tier, 100)
        except Exception:
            pass
    if request.headers.get("x-api-key"):
        # Enforced separately (persisted) in api/auth_utils.py — don't
        # double-count here.
        return "apikey:skip", 10**9
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}", UNAUTH_LIMIT_PER_DAY


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in _UNLIMITED_PATHS:
        return await call_next(request)

    key, limit = _rate_limit_key_and_cap(request)
    now = time.time()
    with _rate_limit_lock:
        window_start, count = _rate_limit_state.get(key, (now, 0))
        if now - window_start >= _RATE_WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        _rate_limit_state[key] = (window_start, count)
        retry_after = max(1, int(_RATE_WINDOW_SECONDS - (now - window_start)))

    if count > limit:
        logger.warning("Rate limit exceeded for %s (%d/%d per day)", key, count, limit)
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded ({limit}/day)"},
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    logger.info("%s %s → %d (%dms)", request.method, request.url.path,
                response.status_code, int((time.monotonic()-t0)*1000))
    return response

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    # No separate sentry_sdk.capture_exception() call needed: Sentry's
    # LoggingIntegration is on by default once sentry_sdk.init() has run
    # (see SENTRY_DSN block above) and auto-captures ERROR-level log calls
    # made with exc_info=True, exactly what this already does.
    logger.error("Unhandled: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth_router,      prefix="/v1/auth",      tags=["auth"])
app.include_router(risk_router,      prefix="/v1/risk",      tags=["risk"])
app.include_router(user_router,      prefix="/v1/user",      tags=["user"])
app.include_router(search_router,    prefix="/v1/search",    tags=["search"])
app.include_router(fmcg_router,      prefix="/v1/fmcg",      tags=["fmcg"])
app.include_router(insurance_router, prefix="/v1/insurance", tags=["insurance"])
app.include_router(meta_router,      prefix="/v1/meta",      tags=["meta"])
app.include_router(disputes_router,  prefix="/v1/disputes",  tags=["disputes"])
app.include_router(admin_router,     prefix="/v1/admin",     tags=["admin"])
app.include_router(admin_panel_router, prefix="/v1/admin",   tags=["admin"])
app.include_router(api_keys_router,  prefix="/v1/keys",      tags=["api-keys"])
app.include_router(subscriptions_router, prefix="/v1/subscriptions", tags=["subscriptions"])
app.include_router(disease_router,   prefix="/v1/disease",   tags=["disease"])
app.include_router(trends_router,    prefix="/v1/trends",    tags=["trends"])
app.include_router(compare_router,   prefix="/v1/compare",   tags=["compare"])
app.include_router(reports_router,   prefix="/v1/reports",   tags=["reports"])
app.include_router(admin_reports_router, prefix="/v1/admin", tags=["admin"])
app.include_router(widget_router,    prefix="/v1/widget",    tags=["widget"])
app.include_router(research_router,  prefix="/v1/research",  tags=["research"])
app.include_router(rasff_router,     prefix="/v1/rasff",     tags=["rasff"])

@app.get("/", include_in_schema=False)
async def root():
    return {"service": "FoodSafe India API", "version": "1.1.0", "status": "ok"}
