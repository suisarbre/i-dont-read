def handle(request):
    """Serve a page, from the cache when possible."""
    key = cache_key(request)
    hit = cache.get(key)
    if hit is not None:
        return hit
    row = db.query("SELECT * FROM pages WHERE id = ?", request.page_id)
    page = render(row)
    cache.set(key, page, ttl=300)
    return page
