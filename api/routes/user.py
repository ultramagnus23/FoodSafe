"""
FoodSafe India — User Routes
POST /v1/user/location
GET  /v1/user/profile
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool

user_router = APIRouter()

class LocationUpdate(BaseModel):
    district_id: int

@user_router.post("/location")
async def update_location(body: LocationUpdate, user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET home_district_id = $1 WHERE id = $2",
            body.district_id, user.user_id
        )
        district = await conn.fetchrow(
            "SELECT id, name_canonical, state FROM districts WHERE id = $1", body.district_id
        )
    return {"district_id": district["id"], "district_name": district["name_canonical"], "state": district["state"]}

@user_router.get("/profile")
async def get_profile(user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT email, tier, home_district_id, created_at FROM users WHERE id = $1", user.user_id
        )
    return {"user_id": user.user_id, "email": row["email"], "tier": row["tier"],
            "home_district_id": row["home_district_id"], "created_at": str(row["created_at"])}
