"""Auth smoke route. `GET /v1/whoami` exercises the auth + rate-limit dependencies
end-to-end and is a handy debugging endpoint; the real serving routes land in Stage 06.
"""
from fastapi import APIRouter, Depends

from ..ratelimit import enforce_rate_limit
from .context import AuthContext

router = APIRouter(prefix="/v1", tags=["auth"])


@router.get("/whoami")
async def whoami(ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    return {
        "user_id": ctx.user_id,
        "key_id": ctx.key_id,
        "kind": ctx.kind,
        "end_user": ctx.end_user,
        "rate_per_hour": ctx.rate_per_hour,
    }
