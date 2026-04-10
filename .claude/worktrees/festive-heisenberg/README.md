<p align="center">
  <h1 align="center">MoneyPrinter</h1>
  <p align="center">Automated content creation and monetization pipeline powered by local AI</p>
</p>

<p align="center">
  <a href="https://github.com/s106062228/moneyprinter/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/s106062228/moneyprinter/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI" alt="CI Status" /></a>
  <a href="https://github.com/s106062228/moneyprinter/blob/main/LICENSE"><img src="https://img.shields.io/github/license/s106062228/moneyprinter?style=for-the-badge&color=blue" alt="License" /></a>
  <a href="https://github.com/s106062228/moneyprinter/stargazers"><img src="https://img.shields.io/github/stars/s106062228/moneyprinter?style=for-the-badge&color=yellow" alt="Stars" /></a>
  <a href="https://github.com/s106062228/moneyprinter/issues"><img src="https://img.shields.io/github/issues/s106062228/moneyprinter?style=for-the-badge&color=red" alt="Issues" /></a>
  <a href="https://github.com/s106062228/moneyprinter/pulls"><img src="https://img.shields.io/github/issues-pr/s106062228/moneyprinter?style=for-the-badge&color=green" alt="Pull Requests" /></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/security-14x%20audited-brightgreen?style=for-the-badge&logo=shieldsdotio&logoColor=white" alt="Security: 14x Audited" />
  <img src="https://img.shields.io/badge/tests-425%2B%20passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests: 425+ Passed" />
  <img src="https://img.shields.io/badge/coverage-tracked-blue?style=for-the-badge&logo=codecov&logoColor=white" alt="Coverage Tracked" />
  <img src="https://img.shields.io/badge/LLM-multi--provider-blueviolet?style=for-the-badge&logo=openai&logoColor=white" alt="Multi-LLM Provider" />
</p>

---

MoneyPrinter is an open-source automation tool that generates and publishes short-form video content across multiple platforms. It supports **multiple LLM providers** — [Ollama](https://ollama.com) (local), [OpenAI](https://openai.com), [Anthropic](https://anthropic.com), and [Groq](https://groq.com) — for script generation, [KittenTTS](https://github.com/KittenML/KittenTTS) for text-to-speech, and Selenium for automated uploads.

> Originally forked from [FujiwaraChoki/MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2). Actively maintained with new features, security hardening, and multi-platform support.

## Features

- **YouTube Shorts Automation** — Generate topics, scripts, AI images, voiceovers, and subtitles, then upload directly to YouTube Studio
- **Instagram Reels** — Upload generated videos as Instagram Reels via the instagrapi library with session persistence, caption generation, and hashtag injection
- **TikTok Upload** — Cross-post generated videos to TikTok via web automation
- **Twitter/X Bot** — Generate and post AI-written tweets on a schedule (CRON support)
- **Affiliate Marketing** — Scrape Amazon product info, generate marketing pitches, and auto-post to Twitter
- **Business Outreach** — Scrape Google Maps for local businesses, extract emails, and send cold outreach
- **Multi-LLM Provider** — Choose from Ollama (local), OpenAI, Anthropic Claude, or Groq for text generation — swap providers with a single config change
- **Local AI First** — Default Ollama integration (Llama, Mistral, Gemma, etc.) — no API keys needed for the core pipeline
- **Docker Ready** — Full Docker and Docker Compose support with Xvfb for headless browser automation
- **Multi-Platform Publisher** — Publish generated content across YouTube, TikTok, Twitter, and Instagram simultaneously with a single command — includes retry logic, analytics tracking, and webhook notifications for each platform
- **SEO Optimizer** — LLM-powered metadata optimization for maximum discoverability: generates keyword-first titles, structured descriptions, tags, hashtags, and scroll-stopping hooks — platform-specific for YouTube, TikTok, and Twitter with configurable language and hashtag count
- **Thumbnail Generator** — Auto-generate professional, click-worthy thumbnails with gradient backgrounds, text overlays with outlines, video frame extraction, and 5 style presets (bold, calm, money, dark, vibrant) — fully configurable via config.json
- **Content Scheduler** — Schedule content publishing for optimal posting times with per-platform time recommendations, repeat scheduling, job persistence, and automatic cleanup — integrates with publisher for execution
- **Webhook Notifications** — Real-time Discord and Slack notifications when content is generated, uploaded, or errors occur — with rate limiting, HTTPS-only validation, and rich embed formatting
- **Analytics Tracking** — Built-in event tracking for all content generation and upload activity
- **Analytics Reports** — Generate cross-platform performance reports with success rates, trend analysis, daily activity charts, and actionable content strategy recommendations
- **Centralized Logging** — All status messages flow through both colored console output and rotating log files
- **Config Caching** — High-performance config system that loads once, not on every call
- **Scheduled Automation** — Built-in CRON job system for hands-off content posting
- **Speech-to-Text** — Local Whisper or cloud AssemblyAI for subtitle generation
- **Image Generation** — Gemini-powered AI image generation for video visuals
- **Retry & Recovery** — Exponential backoff retry system with pipeline stage management for resilient video generation
- **CI/CD Pipeline** — GitHub Actions with automated testing, code coverage reporting, security scanning (Bandit), and code linting (Ruff)
- **Code Coverage** — pytest-cov integration with per-line coverage tracking, HTML reports, and CI threshold enforcement (40% minimum)
- **Context Managers** — All browser classes support `with` statement for automatic resource cleanup (no leaked browser processes)
- **425+ Unit Tests** — Comprehensive pytest suite covering config, validation, analytics, analytics reports, cache, logging, multi-LLM provider, retry logic, webhooks, multi-platform publisher, content scheduler, thumbnail generator, SEO optimizer, Twitter/YouTube cache, and utilities
- **14x Security Audited** — SSRF protection, TOCTOU-safe atomic writes, ZIP traversal hardening, recursion depth limits, email rate limiting, CSV injection prevention, URL bounds validation, webhook URL validation, info disclosure prevention, analytics event rotation, arbitrary file read prevention, email format validation, timeout caps, retry module info disclosure fixes, deserialization validation, path/URL disclosure prevention

## Architecture

```
moneyprinter/
├── .github/workflows/ci.yml  # CI/CD: tests, security scan, linting
├── Dockerfile                 # Docker containerization
├── docker-compose.yml         # Multi-service orchestration
├── src/
│   ├── main.py              # CLI entry point with interactive menu
│   ├── config.py             # Cached configuration management
│   ├── mp_logger.py          # Centralized logging framework
│   ├── status.py             # Console output + logger bridge
│   ├── retry.py              # Retry with exponential backoff + pipeline stages
│   ├── llm_provider.py       # Multi-LLM provider (Ollama/OpenAI/Anthropic/Groq)
│   ├── publisher.py           # Multi-platform content publisher
│   ├── content_scheduler.py   # Scheduled publishing with optimal times
│   ├── seo_optimizer.py        # SEO metadata optimizer (titles, tags, hashtags, hooks)
│   ├── thumbnail.py             # AI thumbnail generator with 5 style presets
│   ├── webhooks.py            # Discord & Slack webhook notifications
│   ├── analytics.py          # Event tracking and metrics (atomic writes)
│   ├── analytics_report.py    # Cross-platform analytics report generator
│   ├── validation.py         # Input validation and security
│   ├── cache.py              # Atomic JSON-based data persistence
│   ├── utils.py              # Helper utilities
│   ├── cron.py               # Headless scheduler runner
│   └── classes/
│       ├── YouTube.py         # Full video generation + upload pipeline
│       ├── TikTok.py          # TikTok video upload automation
│       ├── Twitter.py         # Tweet generation + posting
│       ├── Instagram.py       # Instagram Reels upload via instagrapi
│       ├── AFM.py             # Affiliate marketing (Amazon)
│       ├── Outreach.py        # Google Maps scraping + cold email
│       └── Tts.py             # KittenTTS wrapper
├── tests/                     # pytest unit test suite (425+ tests)
├── config.example.json        # Template configuration
├── scripts/                   # Setup and utility scripts
├── docs/                      # Documentation
└── fonts/                     # Custom fonts for subtitles
```

**Video Generation Pipeline:**

```
LLM Provider (topic) → LLM Provider (script) → SEO Optimizer (metadata) → KittenTTS (audio)
    → Gemini (images) → faster-whisper (subtitles) → MoviePy (composite) → Thumbnail (auto)
    → Multi-Platform Publisher (YouTube + TikTok + Instagram + Twitter)

Supported LLM Providers: Ollama (local) | OpenAI | Anthropic Claude | Groq
```

## Quick Start

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) with at least one model pulled (e.g., `ollama pull llama3.2:3b`)
- Firefox browser (for Selenium automation)
- [ImageMagick](https://imagemagick.org/) (for subtitle rendering)
- [Go](https://golang.org/) (only needed for business outreach feature)

### Installation

```bash
# Clone the repository
git clone https://github.com/s106062228/moneyprinter.git
cd moneyprinter

# Run the automated setup script (macOS/Linux)
bash scripts/setup_local.sh
```

Or set up manually:

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create configuration
cp config.example.json config.json
# Edit config.json with your settings
```

### Docker

Run MoneyPrinter in a Docker container with all dependencies pre-installed:

```bash
# Build and start with Docker Compose
docker compose up -d

# Or build manually
docker build -t moneyprinter .
docker run --shm-size=2g -v ./config.json:/app/config.json moneyprinter
```

The Docker setup includes Firefox ESR, geckodriver, Xvfb (virtual display), and ImageMagick. Environment variables for secrets are passed through automatically — see `docker-compose.yml` for the full configuration.

### Configuration

Edit `config.json` with your settings:

| Field | Description | Required |
|-------|-------------|----------|
| `firefox_profile` | Path to your Firefox profile directory | Yes |
| `llm_provider` | LLM backend: `ollama`, `openai`, `anthropic`, or `groq` | No (default: `ollama`) |
| `ollama_model` | Ollama model name (e.g., `llama3.2:3b`) | If using Ollama |
| `openai_api_key` | OpenAI API key | If using OpenAI |
| `openai_model` | OpenAI model (default: `gpt-4o-mini`) | No |
| `anthropic_api_key` | Anthropic API key | If using Anthropic |
| `anthropic_model` | Anthropic model (default: `claude-sonnet-4-6`) | No |
| `groq_api_key` | Groq API key | If using Groq |
| `groq_model` | Groq model (default: `llama-3.3-70b-versatile`) | No |
| `instagram.username` | Instagram account username | For Instagram |
| `instagram.password` | Instagram account password | For Instagram |
| `imagemagick_path` | Path to ImageMagick binary | Yes |
| `nanobanana2_api_key` | Gemini API key for image generation | For video |
| `assembly_ai_api_key` | AssemblyAI key (if using cloud STT) | Optional |
| `email` | SMTP credentials for outreach | For outreach |
| `webhooks.enabled` | Enable webhook notifications | No (default: `false`) |
| `webhooks.discord_url` | Discord webhook URL | If using Discord |
| `webhooks.slack_url` | Slack incoming webhook URL | If using Slack |
| `webhooks.notify_on` | Event types to notify on | No (default: all) |
| `scheduler.enabled` | Enable content scheduler | No (default: `false`) |
| `scheduler.max_pending_jobs` | Maximum pending scheduled jobs | No (default: `100`) |
| `scheduler.optimal_times` | Per-platform optimal posting times | No (defaults provided) |
| `thumbnail.width` | Thumbnail width in pixels | No (default: `1280`) |
| `thumbnail.height` | Thumbnail height in pixels | No (default: `720`) |
| `thumbnail.style` | Style preset: `bold`, `calm`, `money`, `dark`, `vibrant` | No (default: `bold`) |
| `thumbnail.text_color` | Text color (hex) | No (default: `#FFFFFF`) |
| `thumbnail.outline_color` | Text outline color (hex) | No (default: `#000000`) |
| `thumbnail.outline_width` | Text outline thickness (0-20) | No (default: `4`) |
| `seo.enabled` | Enable SEO optimization | No (default: `true`) |
| `seo.platforms` | Platforms to optimize for | No (default: `["youtube"]`) |
| `seo.language` | Target language for SEO content | No (default: `en`) |
| `seo.include_tags` | Generate YouTube tags | No (default: `true`) |
| `seo.include_hooks` | Generate engagement hooks | No (default: `true`) |
| `seo.hashtag_count` | Number of hashtags (1-15) | No (default: `8`) |

**Security tip:** Sensitive values can also be set via environment variables:

| Environment Variable | Overrides |
|---------------------|-----------|
| `LLM_PROVIDER` | `llm_provider` |
| `OPENAI_API_KEY` | `openai_api_key` |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` |
| `GROQ_API_KEY` | `groq_api_key` |
| `GEMINI_API_KEY` | `nanobanana2_api_key` |
| `ASSEMBLYAI_API_KEY` | `assembly_ai_api_key` |
| `IG_USERNAME` | `instagram.username` |
| `IG_PASSWORD` | `instagram.password` |
| `MP_EMAIL_USERNAME` | `email.username` |
| `MP_EMAIL_PASSWORD` | `email.password` |
| `DISCORD_WEBHOOK_URL` | `webhooks.discord_url` |
| `SLACK_WEBHOOK_URL` | `webhooks.slack_url` |

### Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run preflight checks
python scripts/preflight_local.py

# Start the application
python src/main.py
```

The interactive menu will guide you through:

1. **YouTube Shorts** — Generate and upload videos
2. **Twitter Bot** — Post AI-generated tweets
3. **Affiliate Marketing** — Create and share product pitches
4. **Outreach** — Scrape businesses and send emails
5. **Instagram Reels** — Upload videos as Instagram Reels

### Direct Upload

```bash
# Upload a video directly using the upload script
bash scripts/upload_video.sh
```

### Using the Retry System

MoneyPrinter includes a robust retry system for resilient operations:

```python
from retry import retry, run_pipeline, PipelineStage

# Decorator-based retry with exponential backoff
@retry(max_retries=3, retryable_exceptions=(ConnectionError, TimeoutError))
def upload_video(path):
    ...

# Pipeline-based approach for multi-stage operations
stages = [
    PipelineStage("Generate Topic", youtube.generate_topic),
    PipelineStage("Generate Script", youtube.generate_script),
    PipelineStage("Generate Audio", lambda: tts.synthesize(script), required=False),
]
result = run_pipeline(stages)  # Returns success status, results, and errors
```

### Webhook Notifications

MoneyPrinter can send real-time notifications to Discord and/or Slack when content is generated, uploaded, or when errors occur:

```json
{
  "webhooks": {
    "enabled": true,
    "discord_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN",
    "slack_url": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
    "notify_on": ["video_generated", "video_uploaded", "tweet_posted", "pitch_shared", "error"]
  }
}
```

Or set webhook URLs via environment variables: `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`.

Developers can send notifications from any module:

```python
from webhooks import notify, notify_error

# Send a notification when a video is uploaded
notify("video_uploaded", "youtube", "New video uploaded!", {"title": "My Video", "url": "https://..."})

# Send an error notification
notify_error("Upload failed after 3 retries", platform="youtube")
```

Features: rich Discord embeds with color-coded severity, Slack block kit formatting, rate limiting (1 msg/sec/provider), HTTPS-only URL validation with provider domain checks, and env-var fallbacks for webhook secrets.

### Multi-Platform Publishing

Publish a generated video across multiple platforms simultaneously:

```python
from publisher import ContentPublisher, PublishJob

job = PublishJob(
    video_path="/path/to/video.mp4",
    title="My AI-Generated Short",
    description="Created with MoneyPrinter",
    platforms=["youtube", "tiktok", "twitter"],
)

publisher = ContentPublisher()
results = publisher.publish(job)
# Returns a list of PublishResult objects, one per platform
```

Configure default platforms and retry behavior in `config.json`:

```json
{
  "publisher": {
    "platforms": ["youtube", "tiktok"],
    "retry_failed": true,
    "max_retries": 2
  }
}
```

Features: sequential publishing with error isolation per platform, exponential backoff retry on failure, automatic analytics tracking for each publish event, webhook notifications for successes and failures, input validation (video path, title length, platform whitelist). Supports YouTube, TikTok, Twitter, and Instagram.

### Instagram Reels

Upload generated videos as Instagram Reels via the `instagrapi` library:

```python
from classes.Instagram import Instagram

ig = Instagram(
    account_id="my-account-id",
    nickname="my_account",
    username="my_ig_user",
    password="my_ig_pass",
)

# Upload a Reel
ig.upload_reel(
    video_path="/path/to/video.mp4",
    caption="My AI-generated Reel! #MoneyPrinter #AI #Shorts",
)

# View upload history
reels = ig.get_reels()
for reel in reels:
    print(f"{reel['date']}: {reel['caption'][:50]}...")
```

Configure in `config.json`:

```json
{
  "instagram": {
    "username": "",
    "password": ""
  }
}
```

Or set credentials via environment variables: `IG_USERNAME`, `IG_PASSWORD`.

Features: session persistence (no re-login per upload), atomic cache writes for upload history, analytics integration, caption generation with hashtag injection, video format validation (.mp4/.mov), context manager support, cache size rotation (5000 max entries), input validation (null bytes, path checks, caption length).

### Content Scheduler

Schedule content publishing for optimal posting times:

```python
from content_scheduler import ContentScheduler, ScheduledJob, suggest_next_optimal_time

# Get the next optimal posting time for YouTube
optimal_time = suggest_next_optimal_time("youtube")

# Schedule a video for the optimal time
job = ScheduledJob(
    video_path="/path/to/video.mp4",
    title="My Scheduled Short",
    platforms=["youtube", "tiktok"],
    scheduled_time=optimal_time,
    repeat_interval_hours=24,  # Re-publish daily (0 = one-shot)
)

scheduler = ContentScheduler()
scheduler.add_job(job)

# Execute all pending jobs whose scheduled time has arrived
summary = scheduler.run_pending()
# Returns {"executed": 1, "succeeded": 1, "failed": 0}

# Clean up old completed jobs
scheduler.cleanup_completed(max_age_days=7)
```

Configure optimal posting times per platform in `config.json`:

```json
{
  "scheduler": {
    "enabled": true,
    "max_pending_jobs": 100,
    "optimal_times": {
      "youtube": ["10:00", "14:00", "18:00"],
      "tiktok": ["09:00", "12:00", "19:00"],
      "twitter": ["08:00", "12:00", "17:00"]
    }
  }
}
```

Features: per-platform optimal posting times, repeat scheduling with configurable intervals, atomic job persistence, automatic job cleanup, thread-safe concurrent access, integration with publisher module for actual delivery, input validation (path lengths, platform whitelist, interval caps).

### Thumbnail Generation

Auto-generate professional thumbnails for your videos:

```python
from thumbnail import ThumbnailGenerator

gen = ThumbnailGenerator()
path = gen.generate(
    title="How I Made $10K in 30 Days",
    output_path="/path/to/thumbnail.png",
    style="money",          # bold, calm, money, dark, vibrant
    subtitle="Step by step guide",
)

# Or generate from video metadata with auto-extracted frame
path = gen.generate_from_metadata(
    metadata={"title": "My Video", "description": "A great video."},
    output_dir="/output/",
    video_path="/path/to/video.mp4",  # Extracts frame as background
)
```

Configure in `config.json`:

```json
{
  "thumbnail": {
    "width": 1280,
    "height": 720,
    "style": "bold",
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 4
  }
}
```

Features: 5 style presets with curated gradient palettes, automatic text wrapping and centering, configurable text outline for readability, video frame extraction as background (with blur), atomic file saves, input validation (title length, null bytes, dimension clamping).

### SEO Optimization

Optimize video metadata for maximum discoverability across platforms:

```python
from seo_optimizer import optimize_metadata

result = optimize_metadata(
    subject="How to make money with AI in 2026",
    script="In this video we explore the top AI money-making strategies...",
    niche="finance",
    platform="youtube",  # "youtube", "tiktok", or "twitter"
    language="en",
)

print(result.title)       # SEO-optimized title with power words
print(result.description) # Structured description with hooks and CTAs
print(result.tags)        # 15-20 relevant tags (YouTube only)
print(result.hashtags)    # Platform-specific hashtags
print(result.hooks)       # 3 scroll-stopping opening hooks
print(result.score)       # 0-100 estimated SEO quality score
```

Configure in `config.json`:

```json
{
  "seo": {
    "enabled": true,
    "platforms": ["youtube"],
    "language": "en",
    "include_tags": true,
    "include_hooks": true,
    "hashtag_count": 8
  }
}
```

Features: platform-specific prompts (YouTube, TikTok, Twitter), keyword-first title generation, structured descriptions with CTAs, tag generation with broad/niche/long-tail mix, hashtag strategy with discovery tags, engagement hook generation, SEO quality scoring, rate-limited LLM calls, ReDoS-safe JSON parsing, input validation with null byte checks.

### Analytics Reports

Generate actionable performance reports from your content pipeline:

```python
from analytics_report import generate_report, get_platform_report, save_report

# Full cross-platform report
report = generate_report()
print(report.to_text())  # Human-readable text report

# Platform-specific stats
yt_stats = get_platform_report("youtube")
print(f"Success rate: {yt_stats.success_rate}%")
print(f"Trend: {yt_stats.recent_trend}")

# Save report as JSON
save_report(report, "/path/to/report.json")

# Access structured data
data = report.to_dict()
for rec in report.recommendations:
    print(f"- {rec}")
```

Reports include: per-platform success/failure rates, 7-day activity trends, peak day analysis, most common error types, cross-platform comparison, and actionable recommendations (e.g., "TikTok has a 60% success rate — check credentials", "Only active on YouTube — cross-post to TikTok for 2-3x reach").

### Logging

MoneyPrinter uses a centralized logging framework with both console and file output:

- **Console**: Colored output at INFO level and above
- **File**: Detailed logs at DEBUG level, saved to `.mp/logs/moneyprinter.log`
- **Rotation**: Log files rotate at 5MB with 3 backups
- **Bridge**: All legacy `status.py` calls (error/success/info/warning) now also flow through the logger

Developers can use the logger in any module:

```python
from mp_logger import get_logger
logger = get_logger(__name__)
logger.info("Video generation started")
```

## Testing

MoneyPrinter includes a comprehensive pytest test suite with code coverage tracking:

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests with coverage
cd src && python -m pytest ../tests/ -v

# Run with explicit coverage report
cd src && python -m pytest ../tests/ --cov=. --cov-report=term-missing --cov-report=html:../htmlcov
```

**425+ tests** covering: config loading and caching, input validation (paths, URLs, filenames), analytics tracking, analytics report generation (platform stats, trend analysis, recommendations, JSON serialization), cache CRUD operations (including Twitter and YouTube atomic writes), logging framework, multi-LLM provider system (Ollama/OpenAI/Anthropic/Groq), retry/recovery logic, webhook notifications (Discord/Slack), multi-platform publisher (job validation, platform dispatch, retry logic, analytics/notifications), content scheduler (job lifecycle, persistence, optimal times, thread safety, repeat scheduling), thumbnail generator (color utilities, gradient backgrounds, text wrapping, font loading, style presets, metadata generation, video frame extraction), SEO optimizer (input validation, JSON parsing, title/description/hashtag/tag cleaning, score estimation, platform-specific optimization, config helpers, prompt builders), and utility functions.

Coverage reports are generated automatically in CI and stored as build artifacts. The `.coveragerc` configuration enforces a **40% minimum coverage threshold** — the CI pipeline fails if coverage drops below this level.

## CI/CD

Every push and pull request triggers a GitHub Actions pipeline that runs:

- **Tests + Coverage** — Full pytest suite (425+ tests) with pytest-cov coverage tracking, threshold enforcement (40% min), and XML report artifact upload
- **Security** — Bandit SAST scan + dependency vulnerability check (safety)
- **Linting** — Ruff code quality checks

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml) for the full configuration.

## Security

MoneyPrinter takes security seriously. See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the full audit report (**14 audits completed, 80 findings, 78 fixed**).

Key security measures:

- `config.json` is gitignored to prevent credential leaks
- Environment variable fallbacks for all sensitive configuration
- Input validation on all file paths and URLs
- Safe zip extraction with `os.path.normpath()` path traversal prevention
- No `shell=True` in subprocess calls; no `os.system()` usage
- Timeouts on all HTTP requests
- SSRF protection with internal IP blocking on all outreach requests
- Atomic file writes across ALL cache and data layers (prevents TOCTOU race conditions)
- Shell scripts hardened with `set -euo pipefail` and input validation
- Cron runner validates all command-line arguments
- Email send rate limiting to prevent abuse
- Recursion depth limits on all LLM retry loops
- Information disclosure prevention (no response bodies or full exceptions in logs)
- Automated security scanning in CI (Bandit + safety)
- Unused dependencies removed to minimize attack surface
- Docker containerization with non-root user for isolation
- Context manager protocol on all browser classes to prevent resource leaks
- Atomic CSV writes in outreach email extraction
- Webhook URL validation with HTTPS enforcement and provider domain checks
- Webhook secrets supported via environment variables (never hardcoded)
- Analytics event rotation (10,000 max events) to prevent disk exhaustion
- Publisher input validation (video path, title length, platform whitelist, null byte checks)
- Outreach message body path validation (prevents arbitrary file reads outside project directory)
- Proper email format validation with regex before SMTP sends
- Scraper timeout capped at 1 hour to prevent indefinite process hangs
- Affiliate link URL validation before storage and browser navigation
- Content scheduler job validation (path lengths, platform whitelist, interval caps)
- SEO optimizer input validation (subject/script/niche length caps, null byte checks, platform whitelist)
- ReDoS-safe JSON parsing with response length caps in SEO module
- Rate-limited LLM calls in SEO optimizer to prevent API throttling
- Thread count bounded (1-32) to prevent resource exhaustion
- ScheduledJob deserialization validation (field truncation, platform whitelist, status enum, interval clamping)
- Analytics event query limit bounded (max 10,000) to prevent memory exhaustion
- Pipeline error dict stores only exception class names (no sensitive details)
- Timezone-aware datetime in webhook payloads (Python 3.12+ compliant)
- Analytics query limit safety cap is module-level constant (not overridable by callers)
- LLM prompt length capped at 50,000 characters to prevent API cost abuse
- Lazy imports for heavy dependencies to reduce attack surface and import failures
- Thumbnail output directory validation with null byte checks
- Browser cleanup safety guards in publisher (hasattr checks)
- Instagram session files stored in gitignored `.mp/` directory
- Instagram credentials support environment variable fallbacks (never logged)

To report a security vulnerability, please open a private issue or contact the maintainer directly.

## Roadmap

See [TODO.md](TODO.md) for the full roadmap. Key upcoming features:

- Web dashboard for monitoring
- Content calendar UI (frontend for content scheduler)
- Video template system (custom intros/outros)
- AI hook optimization for viral engagement
- Virality scoring (predict engagement before posting)
- OpusClip-style smart clipping from long-form content
- Shoppable content integration
- Multi-platform export optimizer

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Documentation

- [Configuration Guide](docs/Configuration.md)
- [YouTube Automation](docs/YouTube.md)
- [Twitter Bot](docs/TwitterBot.md)
- [Affiliate Marketing](docs/AffiliateMarketing.md)
- [Security Audit](SECURITY_AUDIT.md)
- [Roadmap](TODO.md)

## License

MoneyPrinter is licensed under the [GNU Affero General Public License v3.0](LICENSE).

## Acknowledgments

- [FujiwaraChoki/MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2) — Original project
- [KittenTTS](https://github.com/KittenML/KittenTTS) — Text-to-speech engine
- [Ollama](https://ollama.com) — Local LLM runtime
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Local speech-to-text

## Disclaimer

This project is for educational purposes only. The author is not responsible for any misuse of the information or tools provided. All automation should comply with the terms of service of the respective platforms. Use responsibly.
