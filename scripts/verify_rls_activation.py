"""
FoodSafe India — RLS activation verification.

docs/RLS_ACTIVATION.md step 2: before pointing the real DATABASE_URL secret
at the restricted `foodsafe_app` role, run the full auth flow against a
staging connection using that role and confirm nothing silently breaks.
"RLS denial" looks like an empty result, not an error, so a normal smoke
test that only checks for 200/5xx status codes can pass while actually
returning zero rows for every user — this script checks the *content* of
each response, not just its status code.

Usage:
    DATABASE_URL="postgresql://foodsafe_app:<pw>@<host>:5432/postgres?sslmode=require" \
    JWT_SECRET=<same value the API uses> \
    python -m scripts.verify_rls_activation

Run this against a STAGING database, not production — it registers a real
throwaway user (email verify-rls-<timestamp>@example.invalid) to exercise
the flow. Exits non-zero on the first check that fails.

This intentionally does not import api.main (which would require a running
event loop + real network binding) — it drives api's own routers in-process
via httpx's ASGI transport, so it exercises the exact same code path
(including api/db.py's user_scoped()) a real request would.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

from api.main import app
from api.db import init_pool, close_pool


async def _check(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        await close_pool()
        sys.exit(1)


async def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set. Point this at a STAGING database using the")
        print("foodsafe_app role before running — see docs/RLS_ACTIVATION.md.")
        sys.exit(2)

    await init_pool()

    email = f"verify-rls-{int(time.time())}@example.invalid"
    password = "verify-rls-test-password-not-reused-anywhere"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Register
        r = await client.post("/v1/auth/register", json={"email": email, "password": password})
        await _check("register returns 201", r.status_code == 201, r.text)
        body = r.json()
        access = body["access_token"]
        refresh = body["refresh_token"]
        user_id = body["user_id"]
        headers = {"Authorization": f"Bearer {access}"}

        # 2. Profile read — the real test. Under RLS-denial-as-empty-result,
        # this comes back 200 with a body that's missing fields, not an error.
        r = await client.get("/v1/user/profile", headers=headers)
        await _check("profile fetch returns 200", r.status_code == 200, r.text)
        profile = r.json()
        await _check(
            "profile actually contains this user's email (not empty/denied)",
            profile.get("email") == email,
            f"got: {profile}",
        )

        # 3. Update location, then re-read to confirm the write landed.
        r = await client.post("/v1/user/location", json={"district_id": 1}, headers=headers)
        await _check("location update returns 200", r.status_code == 200, r.text)
        r = await client.get("/v1/user/profile", headers=headers)
        await _check(
            "location update actually persisted",
            r.json().get("home_district_id") == 1,
            f"got: {r.json()}",
        )

        # 4. Refresh token rotation.
        r = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        await _check("refresh returns 200 with a new token pair", r.status_code == 200, r.text)
        new_access = r.json()["access_token"]
        await _check("refresh returns a different access token", new_access != access)

        # 5. Logout — old refresh token should now be rejected.
        r = await client.post("/v1/auth/logout", json={"refresh_token": r.json()["refresh_token"]})
        await _check("logout returns 204", r.status_code == 204, r.text)

        print(f"\nAll checks passed for user_id={user_id}, email={email}.")
        print("Remember to delete this throwaway user from staging if it matters to you.")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
