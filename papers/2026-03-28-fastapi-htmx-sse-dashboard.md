# FastAPI + HTMX + SSE Dashboard Pattern (2026)

## Summary
Zero-JavaScript real-time dashboard using FastAPI native SSE + HTMX for DOM updates + Jinja2 for server-side rendering.

## Key Architecture
- FastAPI `EventSourceResponse` streams events (native since v0.135.0)
- HTMX SSE extension listens and swaps HTML fragments (14KB total frontend)
- Jinja2 templates render server-side, shipped as HTML fragments
- Performance: 92% lower TTI vs React (45ms vs 650ms)

## Reference Implementations
- https://github.com/vlcinsky/fastapi-sse-htmx (minimal demo)
- https://github.com/volfpeter/fastapi-htmx-tailwind-example (IoT dashboard)
- https://github.com/volfpeter/fasthx (declarative SSR library)

## Production Patterns
- Redis pub/sub for horizontal scaling
- Health/readiness endpoints for automated recovery
- 5-10s scrape intervals for near-real-time metrics
- Connection resumption via Last-Event-ID header

## Relevance to MPV2
Dashboard backend can be built with FastAPI + Jinja2 + HTMX. Zero new frontend deps. Reads from existing analytics.py and cache.py data stores. Estimated ~200 lines of backend code + templates.
