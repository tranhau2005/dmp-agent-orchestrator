from redis.asyncio import Redis


def make_redis_client(redis_url: str) -> Redis:
    return Redis.from_url(redis_url)
