# FastAPI Native SSE for Real-Time Dashboards
**Date**: 2026-03-27

## FastAPI SSE Support (v0.135.0+)

### Key Pattern
from fastapi.sse import EventSourceResponse, ServerSentEvent
@app.get("/stream", response_class=EventSourceResponse)
async def stream() -> AsyncIterable[ServerSentEvent]:
    yield ServerSentEvent(data=payload, event="job_update", id=str(i))

### Built-in Features
- Keep-alive pings (15s), Cache-Control, X-Accel-Buffering
- Connection resumption via Last-Event-ID
- Works with GET and POST, zero extra deps

### Dashboard Endpoints for MPV2
- GET /api/jobs/stream — SSE job status updates
- GET /api/analytics/stream — real-time analytics
- GET /api/health — pipeline health
- GET /api/dashboard — current state

## Sources
- https://fastapi.tiangolo.com/tutorial/server-sent-events/
