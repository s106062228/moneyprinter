# Hypotheses — MoneyPrinter Research Pipeline
## Generated: 2026-03-27

Based on survey findings (see JOURNAL.md 2026-03-27).

---

### H1: Smart Clipping Module (PySceneDetect Integration)
**Priority: HIGH**
**Hypothesis**: Adding a smart clipping module using PySceneDetect to detect scenes in long-form video and extract highlight segments will provide the foundational capability for the planned "OpusClip-style smart clipping" roadmap item.
**Metric**: Module passes unit tests with >80% coverage; correctly detects scene boundaries in sample videos; generates clips of configurable duration.
**Status**: UNTESTED

### H2: Web Dashboard Backend (FastAPI + SSE)
**Priority: HIGH**
**Hypothesis**: A FastAPI-based monitoring backend with Server-Sent Events can expose real-time analytics, job status, and pipeline health, enabling the planned "Web dashboard for monitoring content generation" roadmap item. FastAPI is the natural fit given the existing Python stack.
**Metric**: API serves analytics data and job status; SSE endpoint streams real-time updates; unit tests pass with >80% coverage; response time <200ms for dashboard endpoints.
**Status**: UNTESTED

### H3: Enhanced Content Scheduler with ML-Based Optimal Timing
**Priority: MEDIUM**
**Hypothesis**: Enriching the existing content_scheduler.py with platform-specific engagement-weighted time slots (based on 2026 platform data) will improve scheduling recommendations. Current hardcoded optimal times can be replaced with data-driven defaults.
**Metric**: Updated optimal time defaults reflect 2026 research data; scheduling algorithm considers platform-specific engagement windows; existing tests continue to pass; new tests validate improved time selection.
**Status**: UNTESTED

### H4: A/B Testing Framework for Titles and Thumbnails
**Priority: MEDIUM**
**Hypothesis**: Adding a lightweight A/B testing module that generates variant titles/thumbnails and tracks which variants perform better will lay groundwork for the roadmap's "A/B testing for video titles and thumbnails" item. Can integrate with existing thumbnail.py and seo_optimizer.py.
**Metric**: Module generates N title/thumbnail variants per video; tracks variant selection and maps to analytics events; unit tests pass with >80% coverage.
**Status**: UNTESTED

### H5: Batch Generator Integration Tests
**Priority: HIGH** (immediate — listed as "In Progress" in TODO.md)
**Hypothesis**: Adding comprehensive edge case and integration tests for batch_generator.py will increase overall test coverage and catch boundary conditions (empty topics, max batch size, publish failures, concurrent runs).
**Metric**: 15+ new tests; batch_generator coverage >80%; all existing 535+ tests continue to pass; CI pipeline remains green.
**Status**: UNTESTED

### H6: Content Template CLI Integration
**Priority: LOW**
**Hypothesis**: Adding a menu option to main.py for content template management (CRUD) will make the existing content_templates.py module accessible to users without code changes, addressing the "Content template CLI integration" roadmap item.
**Metric**: New menu option in main.py; users can list/create/edit/delete templates interactively; integration test validates the flow.
**Status**: UNTESTED

---

## Priority Ranking
1. **H5** — Batch generator tests (in-progress roadmap item, low risk, high value)
2. **H1** — Smart clipping module (high-impact new capability, clear implementation path)
3. **H2** — Web dashboard backend (high-priority roadmap item, significant scope)
4. **H3** — Enhanced scheduler timing (medium effort, improves existing module)
5. **H4** — A/B testing framework (medium priority, depends on analytics data)
6. **H6** — Template CLI (low priority, quality-of-life improvement)

## Implementation Recommendation
Focus this iteration on **H5** (batch generator tests) and **H3** (scheduler timing update) — both are low-risk, high-value, and can be completed + validated within the pipeline runtime. Defer H1, H2, H4, H6 to future iterations as they require larger architectural changes.

---

## Evaluation — 2026-03-27

### H5: Batch Generator Edge Case & Integration Tests — CONFIRMED
- **Result**: 22 new tests added (47 total), all passing
- **Coverage**: 88.27% for batch_generator.py (target was >80%)
- **Edge cases covered**: whitespace topics, non-string inputs, max-length boundaries, duplicate topics, auto-publish flows, exception handling, analytics tracking, sleep timing
- **Verdict**: Hypothesis confirmed. Comprehensive edge case coverage achieved.

### H3: Enhanced Content Scheduler with 2026 Optimal Timing — CONFIRMED
- **Result**: Default optimal times updated to match 2026 research data
- **New feature**: `_DAY_WEIGHTS` dict + `get_best_posting_time()` function
- **Coverage**: 91.37% for content_scheduler.py
- **Tests**: 15 new tests, all passing. Also fixed 3 pre-existing timezone bugs in test suite.
- **Verdict**: Hypothesis confirmed. Scheduler now uses research-backed timing data.

### H1: Smart Clipping Module — DEFERRED
- Not implemented this iteration. Scoped for future work with PySceneDetect.

### H2: Web Dashboard Backend — DEFERRED
- Not implemented this iteration. Requires larger architectural effort.

### H4: A/B Testing Framework — DEFERRED
- Not implemented this iteration. Requires analytics data pipeline.

### H6: Content Template CLI — DEFERRED
- Not implemented this iteration. Low priority quality-of-life improvement.
