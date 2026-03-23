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
  <img src="https://img.shields.io/badge/security-7x%20audited-brightgreen?style=for-the-badge&logo=shieldsdotio&logoColor=white" alt="Security: 7x Audited" />
  <img src="https://img.shields.io/badge/tests-183%20passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests: 183 Passed" />
  <img src="https://img.shields.io/badge/coverage-tracked-blue?style=for-the-badge&logo=codecov&logoColor=white" alt="Coverage Tracked" />
  <img src="https://img.shields.io/badge/LLM-multi--provider-blueviolet?style=for-the-badge&logo=openai&logoColor=white" alt="Multi-LLM Provider" />
</p>

---

MoneyPrinter is an open-source automation tool that generates and publishes short-form video content across multiple platforms. It supports **multiple LLM providers** — [Ollama](https://ollama.com) (local), [OpenAI](https://openai.com), [Anthropic](https://anthropic.com), and [Groq](https://groq.com) — for script generation, [KittenTTS](https://github.com/KittenML/KittenTTS) for text-to-speech, and Selenium for automated uploads.

> Originally forked from [FujiwaraChoki/MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2). Actively maintained with new features, security hardening, and multi-platform support.

## Features

- **YouTube Shorts Automation** — Generate topics, scripts, AI images, voiceovers, and subtitles, then upload directly to YouTube Studio
- **TikTok Upload** — Cross-post generated videos to TikTok via web automation
- **Twitter/X Bot** — Generate and post AI-written tweets on a schedule (CRON support)
- **Affiliate Marketing** — Scrape Amazon product info, generate marketing pitches, and auto-post to Twitter
- **Business Outreach** — Scrape Google Maps for local businesses, extract emails, and send cold outreach
- **Multi-LLM Provider** — Choose from Ollama (local), OpenAI, Anthropic Claude, or Groq for text generation — swap providers with a single config change
- **Local AI First** — Default Ollama integration (Llama, Mistral, Gemma, etc.) — no API keys needed for the core pipeline
- **Docker Ready** — Full Docker and Docker Compose support with Xvfb for headless browser automation
- **Analytics Tracking** — Built-in event tracking for all content generation and upload activity
- **Centralized Logging** — All status messages flow through both colored console output and rotating log files
- **Config Caching** — High-performance config system that loads once, not on every call
- **Scheduled Automation** — Built-in CRON job system for hands-off content posting
- **Speech-to-Text** — Local Whisper or cloud AssemblyAI for subtitle generation
- **Image Generation** — Gemini-powered AI image generation for video visuals
- **Retry & Recovery** — Exponential backoff retry system with pipeline stage management for resilient video generation
- **CI/CD Pipeline** — GitHub Actions with automated testing, code coverage reporting, security scanning (Bandit), and code linting (Ruff)
- **Code Coverage** — pytest-cov integration with per-line coverage tracking, HTML reports, and CI threshold enforcement (40% minimum)
- **Context Managers** — All browser classes support `with` statement for automatic resource cleanup (no leaked browser processes)
- **183 Unit Tests** — Comprehensive pytest suite covering config, validation, analytics, cache, logging, multi-LLM provider, retry logic, Twitter/YouTube cache, and utilities
- **7x Security Audited** — SSRF protection, TOCTOU-safe atomic writes, ZIP traversal hardening, recursion depth limits, email rate limiting, CSV injection prevention, URL bounds validation, info disclosure prevention

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
│   ├── analytics.py          # Event tracking and metrics (atomic writes)
│   ├── validation.py         # Input validation and security
│   ├── cache.py              # Atomic JSON-based data persistence
│   ├── utils.py              # Helper utilities
│   ├── cron.py               # Headless scheduler runner
│   └── classes/
│       ├── YouTube.py         # Full video generation + upload pipeline
│       ├── TikTok.py          # TikTok video upload automation
│       ├── Twitter.py         # Tweet generation + posting
│       ├── AFM.py             # Affiliate marketing (Amazon)
│       ├── Outreach.py        # Google Maps scraping + cold email
│       └── Tts.py             # KittenTTS wrapper
├── tests/                     # pytest unit test suite (183 tests)
├── config.example.json        # Template configuration
├── scripts/                   # Setup and utility scripts
├── docs/                      # Documentation
└── fonts/                     # Custom fonts for subtitles
```

**Video Generation Pipeline:**

```
LLM Provider (topic) → LLM Provider (script) → KittenTTS (audio) → Gemini (images)
    → faster-whisper (subtitles) → MoviePy (composite) → Selenium (upload)

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
| `imagemagick_path` | Path to ImageMagick binary | Yes |
| `nanobanana2_api_key` | Gemini API key for image generation | For video |
| `assembly_ai_api_key` | AssemblyAI key (if using cloud STT) | Optional |
| `email` | SMTP credentials for outreach | For outreach |

**Security tip:** Sensitive values can also be set via environment variables:

| Environment Variable | Overrides |
|---------------------|-----------|
| `LLM_PROVIDER` | `llm_provider` |
| `OPENAI_API_KEY` | `openai_api_key` |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` |
| `GROQ_API_KEY` | `groq_api_key` |
| `GEMINI_API_KEY` | `nanobanana2_api_key` |
| `ASSEMBLYAI_API_KEY` | `assembly_ai_api_key` |
| `MP_EMAIL_USERNAME` | `email.username` |
| `MP_EMAIL_PASSWORD` | `email.password` |

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

**183 tests** covering: config loading and caching, input validation (paths, URLs, filenames), analytics tracking, cache CRUD operations (including Twitter and YouTube atomic writes), logging framework, multi-LLM provider system (Ollama/OpenAI/Anthropic/Groq), retry/recovery logic, and utility functions.

Coverage reports are generated automatically in CI and stored as build artifacts. The `.coveragerc` configuration enforces a **40% minimum coverage threshold** — the CI pipeline fails if coverage drops below this level.

## CI/CD

Every push and pull request triggers a GitHub Actions pipeline that runs:

- **Tests + Coverage** — Full pytest suite (183 tests) with pytest-cov coverage tracking, threshold enforcement (40% min), and XML report artifact upload
- **Security** — Bandit SAST scan + dependency vulnerability check (safety)
- **Linting** — Ruff code quality checks

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml) for the full configuration.

## Security

MoneyPrinter takes security seriously. See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the full audit report (**7 audits completed, 44 findings, 43 fixed**).

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

To report a security vulnerability, please open a private issue or contact the maintainer directly.

## Roadmap

See [TODO.md](TODO.md) for the full roadmap. Key upcoming features:

- Instagram Reels upload integration
- Multi-platform simultaneous posting
- Web dashboard for monitoring
- Video template system (custom intros/outros)
- AI hook optimization for viral engagement
- Virality scoring (predict engagement before posting)

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
