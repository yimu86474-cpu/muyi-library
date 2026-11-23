"""The resource route list and a single exact-match dispatcher.

A handler returning None has already responded. UNHANDLED alone means no route
matched, so a response can never accidentally fall through to the static page.
"""
from . import api_sources, api_assets, api_collections, api_captures

UNHANDLED = object()
ROUTES = (
    *api_sources.ROUTES,
    *api_assets.ROUTES,
    *api_collections.ROUTES,
    *api_captures.ROUTES,
)


def dispatch(request, app, method, parsed, query):
    for expected_method, pattern, handler in ROUTES:
        if expected_method not in (method, "*"):
            continue
        match = pattern.fullmatch(parsed.path)
        if match is not None:
            return handler(request, app, parsed, query, match)
    return UNHANDLED
