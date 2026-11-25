"""
Rate limiting (tiêu chí 7).

Sliding window 60 giây lưu trong Redis sorted set theo API key.
"""
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    client = get_redis()
    if client is None:
        raise HTTPException(status_code=503, detail="Rate limiter backend unavailable")

    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"rate_limit:{key}"

    try:
        pipe = client.pipeline(transaction=True)
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            oldest = client.zrange(redis_key, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": limit,
                    "window_seconds": WINDOW_SECONDS,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = client.pipeline(transaction=True)
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 1)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter backend unavailable")
