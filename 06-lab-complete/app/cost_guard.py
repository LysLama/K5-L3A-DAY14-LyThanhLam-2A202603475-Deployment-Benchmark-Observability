"""
Cost guard (tiêu chí 8).

Cộng dồn chi phí LLM (tính theo token) vào Redis và chặn với HTTP 402 khi vượt ngân sách.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    client = get_redis()
    if client is None:
        raise HTTPException(status_code=503, detail="Cost guard backend unavailable")

    try:
        daily_spent = float(client.get(_daily_key()) or 0.0)
        monthly_spent = float(client.get(_monthly_key()) or 0.0)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Cost guard backend unavailable")

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily_spent, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )

    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly_spent, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng trong Redis."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )

    client = get_redis()
    if client is not None:
        try:
            d_key = _daily_key()
            m_key = _monthly_key()
            pipe = client.pipeline(transaction=True)
            pipe.incrbyfloat(d_key, cost)
            pipe.expire(d_key, 2 * 24 * 3600)
            pipe.incrbyfloat(m_key, cost)
            pipe.expire(m_key, 32 * 24 * 3600)
            pipe.execute()
        except redis.RedisError:
            pass

    return cost
