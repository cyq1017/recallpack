def build_upstream_headers(mode, inbound_headers, provider_token):
    headers = dict(inbound_headers)
    if mode == "standard":
        headers["X-Api-Key"] = provider_token
    elif mode == "oauth_code":
        headers["Authorization"] = f"Bearer {provider_token}"
    return headers
