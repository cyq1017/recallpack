DEFAULT_TTL_SECONDS = 300


def build_cache_key(tenant_id, user_id):
    return f"user:{user_id}"
