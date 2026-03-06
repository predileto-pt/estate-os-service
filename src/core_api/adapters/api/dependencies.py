from fastapi import Depends, HTTPException, Request

from core_api.domain.models.user import User


async def get_supabase_user_id(request: Request) -> str:
    user_id = getattr(request.state, "supabase_user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


async def get_current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
