def handle(request):
    """Serve a page."""
    row = db.query("SELECT * FROM pages WHERE id = ?", request.page_id)
    page = render(row)
    return page
