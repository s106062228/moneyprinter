#!/usr/bin/env python3
"""Temporary script to write Ralph config files. Delete after running."""
import os

base = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(base, "specs"), exist_ok=True)

fix_plan = """\
# Ralph Fix Plan

## High Priority

- [ ] **Batch generator edge case tests** — complete integration tests for `batch_generator.py` (in-progress)
- [ ] **Content template CLI** — add template management menu option to `src/main.py` (list/create/edit/delete/generate batch)
- [ ] **Web dashboard backend** — FastAPI app (`src/dashboard/app.py`) with endpoints for live job status, analytics summary, scheduled jobs, log streaming
- [ ] **Web dashboard frontend** — Minimal HTML/JS served by FastAPI; auto-refreshing job status and analytics cards

## Medium Priority

- [ ] **Content calendar UI** — Calendar view in dashboard for scheduled jobs; reuse `content_scheduler.py` API
- [ ] **A/B testing module** — `src/ab_testing.py` with variant storage in `.mp/ab_tests.json`, result tracking, winner detection
- [ ] **AI hook optimization** — `src/hook_optimizer.py` using `llm_provider.generate_text()` to score/rank hook phrases; integrate into YouTube script generation
- [ ] **OpusClip-style smart clipping** — `src/smart_clip.py` using OpenCV scene detection to extract highlight clips with thumbnails
- [ ] **Video template system** — Custom intro/outro support in YouTube pipeline; store paths in `content_templates.py`
- [ ] **Auto-caption styling** — Animated caption presets (CapCut-style) in YouTube subtitle pipeline
- [ ] **Virality scoring** — `src/virality_scorer.py` using LLM to predict engagement score; integrate with publisher

## Low Priority

- [ ] **Multi-platform export optimizer** — platform-specific aspect ratio/format conversion
- [ ] **Shoppable content integration** — product link injection into YouTube/TikTok descriptions
- [ ] **Multi-language dubbing** — AI TTS in multiple languages; extend `src/classes/Tts.py`
- [ ] **Auto-niche detection** — trending topic scraping to suggest niches in main.py menu
- [ ] **Plugin system** — dynamic module loading for custom platform integrations
- [ ] **Encrypt cache files** — encrypt `.mp/*.json` files containing account credentials at rest
- [ ] **Video analytics dashboard** — views/engagement tracking page in web dashboard
- [ ] **Multi-language UI** — i18n for `src/main.py` menu strings
- [ ] **Kubernetes Helm chart** — production-scale deployment manifests
- [ ] **Predictive micro-trend detection** — trend forecasting for topic selection

## Completed
- [x] Project initialization
- [x] YouTube Shorts automation (generate + upload)
- [x] Twitter bot with CRON scheduling
- [x] Affiliate marketing (Amazon + Twitter)
- [x] Business outreach (Google Maps + cold email)
- [x] TikTok upload integration
- [x] Analytics tracking system
- [x] Input validation module
- [x] Security audits (Run 1-16)
- [x] Config caching system
- [x] Centralized logging (`mp_logger.py`)
- [x] Shell script hardening
- [x] Unit test suite (pytest) — 535+ tests
- [x] Atomic cache writes everywhere
- [x] Email send rate limiting
- [x] CI/CD pipeline (GitHub Actions: pytest + Bandit + Ruff + coverage)
- [x] Retry/error recovery module (`retry.py`)
- [x] Docker containerization
- [x] Multi-LLM provider (OpenAI, Anthropic, Groq, Ollama)
- [x] Context manager protocol for browser classes
- [x] Webhook notifications (Discord, Slack)
- [x] Multi-platform publisher (`publisher.py`)
- [x] Content scheduler (`content_scheduler.py`)
- [x] Thumbnail generator (`thumbnail.py`)
- [x] SEO optimizer (`seo_optimizer.py`)
- [x] Analytics report generator (`analytics_report.py`)
- [x] Instagram Reels integration
- [x] Batch video generator (`batch_generator.py`)
- [x] Content template system (`content_templates.py`)
- [x] Full timezone-aware UTC timestamp migration

## Notes
- Start each session by reading `src/` module list to avoid duplicating existing work
- All cache files use atomic write pattern: `tempfile.mkstemp` + `os.replace`
- CI coverage threshold is 40% — new modules must have tests
- Web dashboard accessible via `python src/dashboard/app.py` or a new menu option
- Smart clipping requires `opencv-python` — add to `requirements.txt`
"""

requirements = """\
# Technical Specifications — MoneyPrinterV2 Next Phase

## System Context

MoneyPrinterV2 is a Python 3.12 CLI tool with 535+ unit tests, CI/CD, Docker support,
and 16 completed security audits. The following specifications cover the planned next-phase features.

---

## 1. Web Dashboard

### Goal
Real-time visibility into content generation jobs, scheduled tasks, and analytics without CLI access.

### Architecture
- **Backend**: FastAPI (`src/dashboard/app.py`)
- **Frontend**: Static HTML/JS served by FastAPI (`src/dashboard/static/`)
- **Data sources**: `.mp/*.json` cache files, `content_scheduler.py` API, `analytics_report.py`

### API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Live job queue status |
| GET | `/api/analytics` | Latest analytics summary |
| GET | `/api/jobs` | Scheduled jobs |
| POST | `/api/jobs` | Create a new scheduled job |
| DELETE | `/api/jobs/{job_id}` | Delete a scheduled job |
| GET | `/api/logs` | Recent log entries (tail) |
| GET | `/ws/status` | WebSocket stream for live job updates |

### Frontend Requirements
- Auto-refresh job status every 5 seconds (or WebSocket)
- Analytics summary cards (total posts, success rate, per-platform breakdown)
- Scheduled jobs list with enable/disable toggle
- Log viewer with scroll-lock
- Vanilla JS acceptable; no framework required

### Security
- Bound to `127.0.0.1` only by default (configurable via `config.json`)
- No user-provided data rendered as raw HTML (XSS prevention)
- Optional basic-auth for non-localhost access

---

## 2. Content Calendar UI

### Goal
Visual frontend for `content_scheduler.py` — create, view, edit, delete scheduled jobs on a calendar grid.

### Requirements
- Monthly/weekly calendar view showing scheduled job slots
- Click a slot to create a new job (platform, template, publish time)
- Click an existing job to edit or delete it
- Color-coded by platform (YouTube, Twitter, TikTok, Instagram)
- Served at `/calendar` within the web dashboard
- Job CRUD via existing `/api/jobs` endpoints

---

## 3. OpusClip-Style Smart Clipping

### Module: `src/smart_clip.py`

### Requirements
- Input: video file path
- Scene detection via OpenCV frame differencing or `createBackgroundSubtractorMOG2`
- Score segments by motion intensity (optional: LLM transcript scoring)
- Output top N clips (default 3) as MP4 in `.mp/clips/`
- Generate thumbnail per clip via `src/thumbnail.py`
- Configurable clip duration: 15s–60s default
- Integrate with YouTube pipeline before upload step

### Dependencies to add
- `opencv-python` to `requirements.txt`

### Output structure
```
.mp/clips/
  clip_001.mp4
  clip_001_thumb.png
  clip_002.mp4
  clip_002_thumb.png
```

---

## 4. Content Template CLI

### Goal
Expose `src/content_templates.py` CRUD via `src/main.py` interactive menu.

### Menu: "Manage Content Templates"
1. List all templates
2. Create new template (name, platform, script skeleton, image prompts)
3. Edit existing template
4. Delete template (confirm before delete)
5. Generate batch from template (select template, enter count)
6. Back to main menu

### Notes
- Templates stored in `.mp/templates.json` via existing atomic write
- No new persistence logic required

---

## 5. A/B Testing Module

### Module: `src/ab_testing.py`

### Data Model
```python
@dataclass
class ABTest:
    test_id: str
    created_at: datetime          # timezone-aware UTC
    platform: str                 # "youtube", "twitter", etc.
    test_type: str                # "title", "thumbnail", "hook"
    variant_a: dict               # {"label": str, "value": str}
    variant_b: dict
    results: dict                 # {"a": {"impressions": int, "conversions": int}, ...}
    winner: str | None            # "a", "b", or None
    status: str                   # "active", "concluded"
```

### Requirements
- Persist tests in `.mp/ab_tests.json` (atomic writes)
- Track impressions/conversions per variant
- Winner = higher conversion rate (minimum 10 impressions each)
- Surface in `analytics_report.py` summary
- YouTube pipeline: offer A/B title variants before upload

---

## 6. AI Hook Optimization

### Module: `src/hook_optimizer.py`

### Requirements
- Input: topic/niche string, count N (default 5)
- Generate N hooks via `llm_provider.generate_text()`
- Score each hook 0–10 via LLM
- Return ranked list
- Cache scores in `.mp/hook_cache.json` keyed by `hash(topic+hook)`
- Integrate into YouTube script generation step

### Prompts
Generation: `Generate {n} high-engagement opening hooks for a YouTube Short about: {topic}`
Scoring: `Rate this YouTube hook for engagement potential (0-10, integer only): "{hook}"`

---

## 7. Virality Scoring

### Module: `src/virality_scorer.py`

### Requirements
- Input: title, description, platform, hashtags
- Output: score 0–100 + brief reasoning string
- Uses `llm_provider.generate_text()`
- Log score per post in analytics via publisher integration
- Configurable threshold in `config.json` (`virality_threshold`): warn (not block) if below

---

## Non-Functional Requirements (all new modules)

| Requirement | Rule |
|-------------|------|
| Security | Validate all input; no shell injection; no info disclosure in errors |
| Timestamps | `datetime.now(timezone.utc)` only |
| File writes | Atomic: `tempfile.mkstemp` + `os.replace` |
| Logging | `from mp_logger import get_logger; logger = get_logger(__name__)` |
| Testing | `tests/test_<module>.py` required; maintain CI 40% coverage threshold |
| Dependencies | Pin versions in `requirements.txt`; justify each new dep |

---

## Priority Matrix

| Feature | Impact | Effort | Order |
|---------|--------|--------|-------|
| Batch generator tests | Low | Low | 1 — finish in-progress |
| Content template CLI | Medium | Low | 2 — zero new deps |
| Web dashboard | High | Medium | 3 — unlocks visibility |
| A/B testing | High | Medium | 4 |
| AI hook optimization | High | Low | 5 |
| Smart clipping | High | High | 6 |
| Virality scoring | Medium | Low | 7 |
| Video templates | Medium | Medium | 8 |
| Calendar UI | Medium | Medium | 9 — requires dashboard |
"""

with open(os.path.join(base, "fix_plan.md"), "w") as f:
    f.write(fix_plan)

with open(os.path.join(base, "specs", "requirements.md"), "w") as f:
    f.write(requirements)

print("Done: fix_plan.md and specs/requirements.md written.")
