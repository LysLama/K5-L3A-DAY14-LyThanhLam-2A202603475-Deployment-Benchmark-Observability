"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn khởi động được khi Redis chưa sẵn sàng (không ping Redis lúc import).
"""
import redis

from app.config import settings

r: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global r
    if r is None and settings.redis_url:
        r = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    return r


def redis_healthy() -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False


def close_redis() -> None:
    global r
    if r is not None:
        try:
            r.close()
        except Exception:
            pass
        r = None
