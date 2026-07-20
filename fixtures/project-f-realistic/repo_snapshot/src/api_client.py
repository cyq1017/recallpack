def build_request(path, token, timeout=5):
    return {
        "path": path,
        "headers": {},
        "timeout": timeout,
    }
