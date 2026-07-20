def build_page_request(page, page_size):
    return {"offset": page * page_size, "limit": page_size}
