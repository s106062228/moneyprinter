<p align="center">
  <h1 align="center">MoneyPrinter</h1>
  <p align="center">Automated content creation and monetization pipeline powered by local AI</p>
</p>

<p align="center">
  <a href="https://github.com/s106062228/moneyprinter/blob/main/LICENSE"><img src="https://img.shields.io/github/license/s106062228/moneyprinter?style=for-the-badge&color=blue" alt="License" /></a>
  <a href="https://github.com/s106062228/moneyprinter/stargazers"><img src="https://img.shields.io/github/stars/s106062228/moneyprinter?style=for-the-badge&color=yellow" alt="Stars" /></a>
  <a href="https://github.com/s106062228/moneyprinter/issues"><img src="https://img.shields.io/github/issues/s106062228/moneyprinter?style=for-the-badge&color=red" alt="Issues" /></a>
  <a href="https://github.com/s106062228/moneyprinter/pulls"><img src="https://img.shields.io/github/issues-pr/s106062228/moneyprinter?style=for-the-badge&color=green" alt="Pull Requests" /></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/security-audited-brightgreen?style=for-the-badge&logo=shieldsdotio&logoColor=white" alt="Security Audited" />
  <img src="https://img.shields.io/badge/tests-117%20passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests: 117 Passed" />
</p>

---

MoneyPrinter is an open-source automation tool that generates and publishes short-form video content across multiple platforms. It uses local AI models via [Ollama](https://ollama.com) for script generation, [KittenTTS](https://github.com/KittenML/KittenTTS) for text-to-speech, and Selenium for automated uploads — all running on your machine with no cloud AI dependency.

> Originally forked from [FujiwaraChoki/MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2). Actively maintained with new features, security hardening, and multi-platform support.

## Features

- **YouTube Shorts Automation** — Generate topics, scripts, AI images, voiceovers, and subtitles, then upload directly to YouTube Studio
- **TikTok Upload** — Cross-post generated videos to TikTok via web automation
- **Twitter/X Bot** — Generate and post AI-written tweets on a schedule (CRON support)
- **Affiliate Marketing** — Scrape Amazon product info, generate marketing pitches, and auto-post to Twitter
- **Business Outreach** — Scrape Google Maps for local businesses, extract emails, and send cold outreach
- **Local AI First** — All text generation runs through Ollama (Llama, Mistral, Gemma, etc.) — no API keys needed for the core pipeline
- **Analytics Tracking** — Built-in event tracking for all content generation and upload activity
- **Centralized Logging** — Rotating file logs with colored console output for easy debugging
- **Config Caching** — High-performance config system that loads once, not on every call
- **Scheduled Automation** — Built-in CRON job system for hands-off content posting
- **Speech-to-Text** — Local Whisper or cloud AssemblyAI for subtitle generation
- **Image Generation** — Gemini-powered AI image generation for video visuals
- **117 Unit Tests** — Comprehensive pytest suite covering config, validation, analytics, cache, logging, LLM provider, and utilities
- **3x Security Audited** — SSRF protection, TOCTOU-safe atomic writes, ZIP traversal hardening, email rate limiting

## Architecture

```
moneyprinter/
├── src/
│   ├── main.py              # CLI entry point with interactive menu
│   ├── config.py             # Cached configuration management
│   ├── mp_logger.py          # Centralized logging framework
│   ├── llm_provider.py       # Ollama LLM integration
│   ├── analytics.py          # Event tracking and metrics
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
├── tests/                     # pytest unit test suite (117 tests)
├── config.example.json        # Template configuration
├── scripts/                   # Setup and utility scripts
├── docs/                      # Documentation
└── fonts/                     # Custom fonts for subtitles
```

**Video Generation Pipeline:**

```
Ollama (topic) → Ollama (script) → KittenTTS (audio) → Gemini (images)
    → faster-whisper (subtitles) → MoviePy (composite) → Selenium (upload)
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

### Configuration

Edit `config.json` with your settings:

| Field | Description | Required |
|-------|-------------|----------|
| `firefox_profile` | Path to your Firefox profile directory | Yes |
| `ollama_model` | Ollama model name (e.g., `llama3.2:3b`) | Yes |
| `imagemagick_path` | Path to ImageMagick binary | Yes |
| `nanobanana2_api_key` | Gemini API key for image generation | For video |
| `assembly_ai_api_key` | AssemblyAI key (if using cloud STT) | Optional |
| `email` | SMTP credentials for outreach | For outreach |

**Security tip:** Sensitive values can also be set via environment variables:

| Environment Variable | Overrides |
|---------------------|-----------|
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

### Logging

MoneyPrinter uses a centralized logging framework with both console and file output:

- **Console**: Colored output at INFO level and above
- **File**: Detailed logs at DEBUG level, saved to `.mp/logs/moneyprinter.log`
- **Rotation**: Log files rotate at 5MB with 3 backups

Developers can use the logger in any module:

```python
from mp_logger import get_logger
logger = get_logger(__name__)
logger.info("Video generation started")
```

## Testing

MoneyPrinter includes a comprehensive pytest test suite:

```bash
# Install test dependencies
pip install pytest

# Run all tests
PYTHONPATH=src pytest tests/ -v
```

**117 tests** covering: config loading and caching, input validation (paths, URLs, filenames), analytics tracking, cache CRUD operations, logging framework, LLM provider, and utility functions.

## Security

MoneyPrinter takes security seriously. See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the full audit report (**3 audits completed**).

Key security measures:

- `config.json` is gitignored to prevent credential leaks
- Environment variable fallbacks for all sensitive configuration
- Input validation on all file paths and URLs
- Safe zip extraction with `os.path.normpath()` path traversal prevention
- No `shell=True` in subprocess calls; no `os.system()` usage
- Timeouts on all HTTP requests
- SSRF protection with internal IP blocking on outreach requests
- Atomic file writes in cache layer (prevents TOCTOU race conditions)
- Shell scripts hardened with `set -euo pipefail` and input validation
- Cron runner validates all command-line arguments
- Email send rate limiting to prevent abuse
- Unused dependencies removed to minimize attack surface

To report a security vulnerability, please open a private issue or contact the maintainer directly.

## Roadmap

See [TODO.md](TODO.md) for the full roadmap. Key upcoming features:

- Instagram Reels upload integration
- Multi-platform simultaneous posting
- Docker containerization
- Web dashboard for monitoring
- CI/CD pipeline (GitHub Actions)
- Additional LLM provider support (OpenAI, Anthropic, Groq)
- AI hook optimization for viral engagement
- Auto-captioning with animated styles

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
