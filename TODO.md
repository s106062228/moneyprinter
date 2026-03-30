# MoneyPrinter — Roadmap & TODO

## Completed
- [x] YouTube Shorts automation (generate + upload)
- [x] Twitter bot with CRON scheduling
- [x] Affiliate marketing (Amazon + Twitter)
- [x] Business outreach (Google Maps scraping + cold email)
- [x] TikTok upload integration
- [x] Analytics tracking system
- [x] Input validation module
- [x] Security audit (Run 1)
- [x] Professional README
- [x] Config caching system (no more per-call file reads)
- [x] Centralized logging framework (`mp_logger.py`)
- [x] Security audit (Run 2) — shell injection, file handle leaks, unused deps
- [x] Remove unused `undetected_chromedriver` dependency
- [x] Shell script hardening (`upload_video.sh`)
- [x] Cron argument validation
- [x] Unit test suite (pytest) — 117 tests covering config, validation, analytics, cache, logger, LLM provider, and utils
- [x] Security audit (Run 3) — SSRF fixes, TOCTOU race conditions, ZIP traversal hardening, email rate limiting
- [x] Atomic cache writes (`tempfile.mkstemp` + `os.replace`)
- [x] Email send rate limiting in Outreach
- [x] CI/CD pipeline (GitHub Actions) with pytest + Bandit SAST + dependency scanning + Ruff linting
- [x] Retry and error recovery module (`retry.py`) with exponential backoff + pipeline stages
- [x] Security audit (Run 4) — TikTok TOCTOU fix, Outreach SSRF hardening, recursion depth limits, exception info disclosure fix
- [x] TikTok cache atomic writes
- [x] YouTube pipeline recursion depth limits (generate_script, generate_metadata, generate_prompts)
- [x] Unit tests for retry module (19 new tests, 136 total)
- [x] Docker containerization (Dockerfile + docker-compose.yml with Ollama service)
- [x] Migrate status.py to bridge legacy output to mp_logger (dual console + file logging)
- [x] Migrate Twitter.py and YouTube.py cache writes to atomic pattern (tempfile + os.replace)
- [x] Analytics module atomic writes (TOCTOU fix + atomic save)
- [x] Security audit (Run 5) — Twitter/YouTube/analytics atomic writes, API response info disclosure fixes
- [x] Unit tests for Twitter/YouTube atomic cache (30 new tests, 166 total)
- [x] Multi-LLM provider system (OpenAI, Anthropic, Groq) with unified provider interface
- [x] Security audit (Run 6) — CSV injection fix, URL bounds validation, email regex fix, Firefox profile path validation
- [x] Unit tests for multi-LLM provider (17 new tests, 183 total)
- [x] pytest-cov integration for code coverage tracking in CI
- [x] Context manager protocol for browser classes (YouTube, Twitter, TikTok, AFM)
- [x] Security audit (Run 7) — Non-atomic CSV write, browser resource leaks, exception info disclosure (6 locations), niche length limit, URL leak in error messages
- [x] Coverage reporting with threshold enforcement (40% minimum)
- [x] Coverage artifact upload in CI pipeline
- [x] Webhook notifications (Discord, Slack) with rate limiting and rich formatting
- [x] Security audit (Run 8) — info disclosure in main.py, webhook URL validation, config.example.json updated
- [x] Unit tests for webhook module (40 new tests, 223 total)
- [x] Multi-platform content publisher (`publisher.py`) with cross-platform orchestration, retry logic, analytics integration, and webhook notifications
- [x] Security audit (Run 9) — analytics unbounded growth, config path disclosure, input echo, scraper path disclosure, temp file safety
- [x] Analytics event rotation (10,000 max events to prevent disk exhaustion)
- [x] Unit tests for publisher module (34 new tests, 257 total)
- [x] Content scheduler (`content_scheduler.py`) with optimal posting times, repeat scheduling, job persistence, and publisher integration
- [x] Security audit (Run 10) — arbitrary file read via message body path, email recipient validation, scraper timeout cap, affiliate link validation
- [x] Unit tests for content scheduler (43 new tests, 300 total)
- [x] Thumbnail generator module (`thumbnail.py`) with gradient backgrounds, text overlays, video frame extraction, 5 style presets
- [x] Security audit (Run 11) — retry module info disclosure (5 locations), YouTube URL leak, Outreach subprocess.call fix, mp_logger exception leak
- [x] Unit tests for thumbnail module (38 new tests, 338 total)
- [x] SEO optimizer module (`seo_optimizer.py`) with platform-specific optimization for YouTube, TikTok, Twitter
- [x] Security audit (Run 12) — ReDoS fix, from_dict validation, path disclosure fixes, thread bounds, LLM rate limiting
- [x] Unit tests for SEO optimizer (45+ new tests, 383+ total)
- [x] Analytics report generator (`analytics_report.py`) with cross-platform insights, trend analysis, success rates, and recommendations
- [x] Security audit (Run 13) — ScheduledJob.from_dict() validation, path/URL disclosure fixes, pipeline error string fix, analytics limit bounds, deprecated datetime fix
- [x] Unit tests for analytics report (42+ new tests, 425+ total)
- [x] Instagram Reels upload integration (`src/classes/Instagram.py`) via instagrapi with session persistence, atomic cache, analytics tracking
- [x] Instagram platform support across publisher, scheduler, SEO optimizer, analytics report, webhooks, and cache modules
- [x] Security audit (Run 14) — analytics limit bypass fix, path disclosure fix, prompt length cap, lazy import fix, output_dir validation, browser cleanup safety
- [x] Unit tests for Instagram Reels module (44 new tests, 470+ total)
- [x] Security audit (Run 15) — stale cache test fix, thumbnail null-byte validation, session path collision fix, reel_id length cap
- [x] Batch video generation module (`batch_generator.py`) with topic-based batch runs, auto-publish, delay enforcement, analytics tracking
- [x] Unit tests for batch generator (20+ new tests, 490+ total)
- [x] Content template system (`content_templates.py`) with named templates, CRUD operations, batch job generation, and atomic persistence
- [x] Unit tests for content templates (45+ new tests, 535+ total)
- [x] Security audit (Run 16) — complete deprecated datetime.now() migration across all remaining modules (11 locations in 5 files)
- [x] Complete timezone-aware UTC timestamp migration (zero deprecated datetime.now() calls remaining)
- [x] Unit tests for batch generator edge cases and integration tests (22 new tests, 88.27% coverage)
- [x] Content scheduler 2026 optimal timing update (research-backed posting times + day-of-week weights)
- [x] Fixed 3 pre-existing timezone bugs in content scheduler test suite
- [x] Smart clipping module (`smart_clipper.py`) — PySceneDetect + LLM engagement scoring pipeline
- [x] Unit tests for smart clipper (51 tests, 96.27% coverage)
- [x] Selenium test environment fix — resolved 30 pre-existing cache isolation failures
- [x] Added scenedetect[opencv] dependency to requirements.txt
- [x] Fixed 9 pre-existing test failures (stale assertions for Instagram platform support, lazy import mock targets, hash-based session path assertions)
- [x] Smart clipper video splitting (`split_clips()` method) — ffmpeg clip extraction via PySceneDetect's built-in `split_video_ffmpeg()` API
- [x] Unit tests for smart clipper split_clips (11 new tests, 96.83% coverage, 745 total suite)
- [x] Zero pre-existing test failures remaining (was 9, now 0)
- [x] Web dashboard backend (`src/dashboard.py`) — FastAPI + Jinja2 + HTMX SSE, 5 endpoints, real-time monitoring
- [x] Unit tests for dashboard (26 tests, 88.89% coverage, 786 total suite)
- [x] Smart clipper CLI integration (menu option 7 in main.py for clip extraction)
- [x] Unit tests for smart clipper CLI (15 tests, all passing)
- [x] MCP server for content pipeline tools (`src/mcp_server.py`) — 4 tools via FastMCP 3.0, 100% coverage
- [x] Unit tests for MCP server (32 tests, 100% coverage)
- [x] Fix 4 pre-existing dependency test failures (moviepy v2 import + faster_whisper mock isolation)
- [x] Content template CLI integration (menu option 8 in main.py for template management)
- [x] Unit tests for content template CLI (21 tests, all passing, 839 total suite)
- [x] Full MoviePy v2 migration for YouTube.py (13 API calls migrated, 29 tests, 879 total suite)
- [x] MCP authentication and Streamable HTTP transport (BearerTokenAuth + --token flag, 11 tests)
- [x] Unit tests for MoviePy v2 migration (29 tests, source AST validation)
- [x] Unit tests for MCP HTTP auth (11 tests, all passing)
- [x] Content calendar UI with FullCalendar v6 (4 REST endpoints, calendar.html template)
- [x] Dashboard charts with Chart.js (3 charts: line, doughnut, bar + /api/analytics/chart-data endpoint)
- [x] Unit tests for calendar + chart endpoints (36 new tests, 90.31% dashboard coverage, 915 total suite)
- [x] A/B testing module (`ab_testing.py`) with variant generation, rotation, metrics tracking, winner evaluation
- [x] Calendar drag-and-drop rescheduling (PATCH endpoint + FullCalendar editable)
- [x] Virality scorer module (`virality_scorer.py`) with LLM-based metadata scoring, platform-specific weights
- [x] Unit tests for A/B testing (71 tests, 96.15% coverage), virality scorer (71 tests, 95.29% coverage), PATCH endpoint (12 tests)

## Completed — Iteration 17 (2026-03-30)
- [x] Content watermarker (`content_watermarker.py`) with WatermarkResult, ContentWatermarker, VideoSeal lazy integration (118 tests, 100% coverage) [H53]
- [x] Content quality gate (`quality_gate.py`) with QualityVerdict, ContentQualityGate, 5-dimension LLM scoring, platform weights (149 tests, 94.02% coverage) [H54]
- [x] Repurposing orchestrator (`repurpose_orchestrator.py`) with RepurposeConfig, RepurposeOrchestrator, clip→optimize→publish pipeline (87 tests, 91.83% coverage) [H55]
- [x] Fix test contamination: sys.modules cleanup in test_repurpose_orchestrator.py (+78 pre-existing failures fixed)
- [x] Unit tests: 354 new tests, 2641 total suite, 0 failures [H53, H54, H55]

## Completed — Iteration 16 (2026-03-30)
- [x] Plugin system (`plugin_manager.py`) with pluggy-based hook specs, plugin registration, directory loading (89 tests, 96.08% coverage) [H50]
- [x] Video analytics tracker (`video_analytics.py`) with per-video engagement metrics, trend computation, atomic persistence (102 tests, 94.94% coverage) [H51]
- [x] Configurable rate limiter (`rate_limiter.py`) with token-bucket algorithm, per-key limits, registry, config integration (76 tests, 100% coverage) [H52]
- [x] Unit tests: 267 new tests, 2287 total suite, 0 failures [H50, H51, H52]

## Completed — Iteration 15 (2026-03-30)
- [x] Predictive trend detection: TrendSpyG migration + predict_trends() + _forecast_peak() (37 tests, 91% coverage) [H47]
- [x] Cache encryption at rest: Fernet symmetric encryption via MONEYPRINTER_CACHE_KEY env var (21 tests, 94% coverage) [H48]
- [x] Affiliate link injection: platform-specific link formatting in publisher.py (26 tests, new code fully covered) [H49]
- [x] Unit tests: 84 new tests, 2000 total suite, 0 failures [H47, H48, H49]

## Completed — Iteration 14 (2026-03-30)
- [x] GPU-accelerated FFmpeg (`ffmpeg_utils.py`) with GpuInfo, detect_gpu, _build_hwaccel_flags, use_gpu kwarg + CPU fallback (43 tests, 97.64% coverage) [H44]
- [x] Video perceptual hashing in UniquenessScorer with videohash2 lazy import, Hamming distance, 5-dimension scoring (29 tests, 94.36% coverage) [H45]
- [x] Defensive pytest.importorskip guards for pandas in trend_detector tests (5 tests modified) [H46]
- [x] Unit tests: 74 new tests, 1934 total suite, 0 failures [H44, H45, H46]

## Completed — Iteration 12 (2026-03-29)
- [x] Wire ffmpeg_utils into export_optimizer — replace MoviePy with FFmpeg subprocess (96 tests, 97.98% coverage) [H38]
- [x] Wire ffmpeg_utils into smart_clipper — replace PySceneDetect split with ffmpeg_utils.trim_clip (68 tests, 96.77% coverage) [H39]
- [x] Wire uniqueness_scorer into publisher — pre-publish uniqueness check with block/warn/off modes (56 tests, 63.37% coverage) [H40]
- [x] Unit tests: 52 new tests, 1860 total suite, 5 pre-existing failures [H38, H39, H40]

## Completed — Iteration 11 (2026-03-29)
- [x] FFmpeg direct export utils (`ffmpeg_utils.py`) with VideoInfo, check_ffmpeg, get_video_info, trim_clip, concat_clips, transcode, extract_audio (98 tests, 96.73% coverage) [H35]
- [x] Content uniqueness scorer (`uniqueness_scorer.py`) with UniquenessScore, UniquenessScorer, 4-dimension scoring, rolling history (91 tests, 92.96% coverage) [H36]
- [x] Trend-to-batch pipeline bridge (`trend_batch_bridge.py`) with generate_trending_batch, topics_to_batch_job (60 tests, 93.44% coverage) [H37]
- [x] Unit tests: 249 new tests, 1808 total suite, 0 failures [H35, H36, H37]

## Completed — Iteration 10 (2026-03-29)
- [x] Animated captions module (`animated_captions.py`) with WordTiming, CaptionSegment, CaptionStyle, AnimatedCaptions, 3 styles (96 tests, 99.07% coverage) [H32]
- [x] Pipeline integration layer (`pipeline_integrator.py`) with prepend_intro_outro, generate_hooked_script, export_for_platforms, apply_captions (54 tests, 100% coverage) [H33]
- [x] Trend detector module (`trend_detector.py`) with TopicCandidate, TrendDetector, Google Trends + Reddit (95 tests, 96.88% coverage) [H34]
- [x] Unit tests: 245 new tests, 1559 total suite, 0 failures [H32, H33, H34]

## Completed — Iteration 9 (2026-03-29)
- [x] Video template system (`video_templates.py`) with VideoTemplate, VideoTemplateManager, 3 presets (100 tests, 94.79% coverage) [H29]
- [x] AI hook generator (`hook_generator.py`) with HookResult, HookGenerator, 5 categories, 5 platforms (73 tests, 95.28% coverage) [H30]
- [x] Multi-platform export optimizer (`export_optimizer.py`) with ExportProfile, ExportOptimizer, 6 platform profiles (72 tests, 97.70% coverage) [H31]
- [x] Unit tests: 245 new tests, 1314 total suite, 0 failures [H29, H30, H31]

## Completed — Iteration 8 (2026-03-29)
- [x] A/B testing module (`ab_testing.py`) with ABVariant, ABTest, ABTestManager (71 tests, 96.15% coverage) [H26]
- [x] Calendar drag-and-drop rescheduling (PATCH endpoint + FullCalendar editable + eventDrop) [H27]
- [x] Virality scorer module (`virality_scorer.py`) with LLM-based metadata scoring (71 tests, 95.29% coverage) [H28]
- [x] Unit tests for PATCH endpoint (12 new tests, 91.07% dashboard coverage, 1069 total suite) [H27]

## Completed — Iteration 7 (2026-03-28)
- [x] Add calendar CRUD endpoints to dashboard.py (GET/POST/DELETE /api/calendar/events + GET /calendar) [H24]
- [x] Create calendar.html Jinja2 template with FullCalendar v6 CDN [H24]
- [x] Add GET /api/analytics/chart-data endpoint to dashboard.py [H25]
- [x] Add Chart.js CDN + 3 charts to dashboard.html template [H25]
- [x] Write tests for calendar + chart endpoints (36 tests) [H24, H25]
- [x] Run full test suite (915/915 passing, 0 failures) [H24, H25]

## Completed — Iteration 6 (2026-03-28)
- [x] Update YouTube.py imports from moviepy v1 to v2 (remove editor, fx.all, config) [H21]
- [x] Migrate combine() method to v2 API (set_→with_, crop→cropped, volumex→MultiplyVolume, TextClip args) [H21]
- [x] Write tests for MoviePy v2 migration (29 tests) [H21]
- [x] Add _get_auth() + --token flag for Bearer Token auth to mcp_server.py [H22]
- [x] Write tests for MCP HTTP auth (11 tests) [H22]
- [x] Run full test suite (879/879 passing, 0 failures) [H21, H22]

## Implementation Tasks — Iteration 7 (2026-03-28)
- [x] Add calendar CRUD endpoints to dashboard.py (GET/POST/DELETE /api/calendar/events + GET /calendar) [H24]
- [x] Create calendar.html Jinja2 template with FullCalendar v6 CDN [H24]
- [x] Add GET /api/analytics/chart-data endpoint to dashboard.py [H25]
- [x] Add Chart.js CDN + 3 charts to dashboard.html template [H25]
- [x] Write tests for calendar + chart endpoints (15+ tests) [H24, H25]
- [x] Run full test suite (915/915 passing, 0 failures) [H24, H25]

## Implementation Tasks — Iteration 8 (2026-03-29)
- [x] Create src/ab_testing.py with ABVariant, ABTest, ABTestManager [H26]
- [x] Write tests for ab_testing module (71 tests, 96.15% coverage) [H26]
- [x] Add PATCH /api/calendar/events/{event_id} endpoint to dashboard.py [H27]
- [x] Update calendar.html with editable + eventDrop/eventResize callbacks [H27]
- [x] Write tests for PATCH endpoint (12 tests) [H27]
- [x] Create src/virality_scorer.py with ViralityScore, ViralityScorer [H28]
- [x] Write tests for virality_scorer module (71 tests, 95.29% coverage) [H28]
- [x] Run full test suite (1069/1069 passing, 0 failures) [H26, H27, H28]

## Implementation Tasks — Iteration 9 (2026-03-29)
- [x] Create src/video_templates.py with VideoTemplate, VideoTemplateManager [H29]
- [x] Write tests for video_templates module (100 tests, 94.79% coverage) [H29]
- [x] Create src/hook_generator.py with HookResult, HookGenerator [H30]
- [x] Write tests for hook_generator module (73 tests, 95.28% coverage) [H30]
- [x] Create src/export_optimizer.py with ExportProfile, ExportOptimizer [H31]
- [x] Write tests for export_optimizer module (72 tests, 97.70% coverage) [H31]
- [x] Run full test suite (1314/1314 passing, 0 failures) [H29, H30, H31]

## Implementation Tasks — Iteration 10 (2026-03-29)
- [x] Create src/animated_captions.py with WordTiming, CaptionSegment, CaptionStyle, AnimatedCaptions [H32]
- [x] Write tests for animated_captions module (96 tests, 99.07% coverage) [H32]
- [x] Create src/pipeline_integrator.py with prepend_intro_outro, generate_hooked_script, export_for_platforms, apply_captions [H33]
- [x] Write tests for pipeline_integrator module (54 tests, 100% coverage) [H33]
- [x] Create src/trend_detector.py with TopicCandidate, TrendDetector [H34]
- [x] Write tests for trend_detector module (95 tests, 96.88% coverage) [H34]
- [x] Run full test suite (1559/1559 passing, 0 failures) [H32, H33, H34]

## Implementation Tasks — Iteration 11 (2026-03-29)
- [x] Create src/ffmpeg_utils.py with VideoInfo, check_ffmpeg, get_video_info, trim_clip, concat_clips, transcode, extract_audio [H35]
- [x] Write tests for ffmpeg_utils module (98 tests, 96.73% coverage) [H35]
- [x] Create src/uniqueness_scorer.py with UniquenessScore, UniquenessScorer, 4-dimension scoring [H36]
- [x] Write tests for uniqueness_scorer module (91 tests, 92.96% coverage) [H36]
- [x] Create src/trend_batch_bridge.py with generate_trending_batch, topics_to_batch_job [H37]
- [x] Write tests for trend_batch_bridge module (60 tests, 93.44% coverage) [H37]
- [x] Run full test suite (1808/1808 passing, 0 failures) [H35, H36, H37]

## Implementation Tasks — Iteration 12 (2026-03-29)
- [x] Replace MoviePy with ffmpeg_utils in export_optimizer.py optimize_clip() [H38]
- [x] Update tests for export_optimizer FFmpeg backend (24 new tests, 96 total, 97.98% cov) [H38]
- [x] Replace PySceneDetect split_video_ffmpeg with ffmpeg_utils.trim_clip in smart_clipper.py [H39]
- [x] Update tests for smart_clipper split_clips (15 new tests, 68 total, 96.77% cov) [H39]
- [x] Add uniqueness check to publisher.py publish() with block/warn/off modes [H40]
- [x] Add optional script field to PublishJob dataclass [H40]
- [x] Write tests for publisher uniqueness integration (23 new tests, 56 total, 63.37% cov) [H40]
- [x] Run full test suite (1855/1860 passing, 5 pre-existing failures) [H38, H39, H40]

## Implementation Tasks — Iteration 13 (2026-03-29) — Superseded by Iteration 14

## Implementation Tasks — Iteration 14 (2026-03-30)
- [x] Add pytest.importorskip("pandas") to 5 trend_detector tests [H46]
- [x] Add GpuInfo namedtuple + _GPU_CODECS constant to ffmpeg_utils.py [H44]
- [x] Add detect_gpu() function to ffmpeg_utils.py [H44]
- [x] Add _build_hwaccel_flags() helper to ffmpeg_utils.py [H44]
- [x] Add use_gpu kwarg to trim_clip/transcode/concat_clips with CPU fallback [H44]
- [x] Write tests for GPU-accelerated FFmpeg (43 tests, 97.64% coverage) [H44]
- [x] Add video_similarity field to UniquenessScore + weight constants [H45]
- [x] Add _compute_video_hash() and _score_video_similarity() helpers [H45]
- [x] Update score_content() and add_to_history() with video_path param [H45]
- [x] Write tests for video perceptual hashing (29 tests, 94.36% coverage) [H45]
- [x] Run full test suite (1934/1934 passing, 0 failures) [H44, H45, H46]

## Implementation Tasks — Iteration 15 (2026-03-30)
- [x] Replace pytrends with trendspyg in fetch_google_trends() [H47]
- [x] Add predicted_peak field to TopicCandidate dataclass [H47]
- [x] Add predict_trends() method with linear regression forecasting [H47]
- [x] Add _forecast_peak() static helper [H47]
- [x] Write tests for TrendSpyG migration + predictive detection (37 tests, 97.11% coverage) [H47]
- [x] Add _get_fernet() + _encrypt_bytes() + _decrypt_bytes() helpers to cache.py [H48]
- [x] Modify _safe_write_json() and _safe_read_json() for Fernet encryption [H48]
- [x] Write tests for cache encryption (21 tests, 94.29% coverage) [H48]
- [x] Add affiliate_links field to PublishJob + _format_affiliate_links() helper [H49]
- [x] Modify publish() to append affiliate links to description [H49]
- [x] Write tests for affiliate link injection (26 tests, >85% coverage) [H49]
- [x] Run full test suite (2000/2000 passing, 0 failures) [H47, H48, H49]

## Implementation Tasks — Iteration 16 (2026-03-30)
- [x] Add pluggy>=1.5.0 to requirements.txt [H50]
- [x] Create src/plugin_manager.py with MoneyPrinterSpec, PluginManager [H50]
- [x] Write tests for plugin_manager module (89 tests, 96.08% coverage) [H50]
- [x] Create src/video_analytics.py with VideoMetrics, VideoAnalyticsTracker [H51]
- [x] Write tests for video_analytics module (102 tests, 94.94% coverage) [H51]
- [x] Create src/rate_limiter.py with RateLimiter, RateLimiterRegistry [H52]
- [x] Write tests for rate_limiter module (76 tests, 100% coverage) [H52]
- [x] Run full test suite (2287/2287 passing, 0 failures) [H50, H51, H52]

## Implementation Tasks — Iteration 17 (2026-03-30)
- [x] Create src/content_watermarker.py with WatermarkResult, ContentWatermarker [H53]
- [x] Write tests for content_watermarker module (118 tests, 100% coverage) [H53]
- [x] Create src/quality_gate.py with QualityVerdict, ContentQualityGate [H54]
- [x] Write tests for quality_gate module (149 tests, 94.02% coverage) [H54]
- [x] Create src/repurpose_orchestrator.py with RepurposeConfig, RepurposeOrchestrator [H55]
- [x] Write tests for repurpose_orchestrator module (87 tests, 91.83% coverage) [H55]
- [x] Fix test contamination: sys.modules cleanup in test_repurpose_orchestrator.py (+78 pre-existing failures fixed)
- [x] Run full test suite (2641/2641 passing, 0 failures) [H53, H54, H55]

## Completed — Iteration 18 (2026-03-30)
- [x] Add get_quality_gate_mode() and get_watermark_enabled() helpers to publisher.py [H56]
- [x] Add _check_quality_gate() method to ContentPublisher [H56]
- [x] Add _apply_watermark() method to ContentPublisher [H56]
- [x] Wire hooks into publish() flow between validate() and _check_uniqueness() [H56]
- [x] Write tests for publisher pre-publish hooks (23 new tests, 71.68% coverage) [H56]
- [x] Add _protect_sys_modules session fixture + mock_optional_dep() helper to conftest.py [H57]
- [x] Add atexit cleanup to 5 test files (smart_clipper, pipeline_integrator, mcp_server, mcp_http_auth, llm_provider) [H57]
- [x] Run full test suite to verify zero regressions (2763 passing) [H57]
- [x] Create src/pipeline_health.py with ModuleHealth + PipelineHealthMonitor [H58]
- [x] Write tests for pipeline_health module (99 tests, 93.01% coverage) [H58]
- [x] Run full test suite (2763/2763 passing, 0 failures) [H56, H57, H58]

## Completed — Iteration 19 (2026-03-31)
- [x] Add 6 lifecycle hookspecs to MoneyPrinterSpec in plugin_manager.py [H61]
- [x] Write tests for lifecycle hookspecs (13 tests) [H61]
- [x] Add _get_health_monitor() lazy singleton + report_health() in publisher.py [H59]
- [x] Add _get_health_monitor() + report_health() in content_scheduler.py [H59]
- [x] Add _get_health_monitor() + report_health() in batch_generator.py [H59]
- [x] Write tests for health reporting in publisher/scheduler/batch (14 tests) [H59]
- [x] Add _get_pipeline_module_health() helper to dashboard.py [H60]
- [x] Add GET /api/health/liveness endpoint to dashboard.py [H60]
- [x] Add GET /api/health/readiness endpoint to dashboard.py [H60]
- [x] Augment GET /api/health with pipeline module data [H60]
- [x] Write tests for dashboard health endpoints (10 tests) [H60]
- [x] Wire plugin dispatch into publisher.py (on_pre_publish, on_post_publish) [H61]
- [x] Wire plugin dispatch into content_scheduler.py (on_pre_schedule, on_post_schedule) [H61]
- [x] Wire plugin dispatch into batch_generator.py (on_batch_start, on_batch_complete) [H61]
- [x] Write tests for plugin dispatch wiring (11 tests) [H61]
- [x] Run full test suite (2791/2791 passing, 0 failures) [H59, H60, H61]

## Planned — High Priority
- [x] Content calendar UI (frontend for content scheduler) — DONE (iteration 7)
- [x] Dashboard frontend polish (charts, job management, content calendar view) — DONE (iteration 7)

## Planned — Medium Priority
- [x] Video template system (custom intros/outros) — DONE (iteration 9)
- [x] A/B testing for video titles and thumbnails — DONE (iteration 8)
- [x] AI hook optimization (trending hooks for better engagement) — DONE (iteration 9)
- [x] Auto-caption styling (animated captions like CapCut) — DONE (iteration 10)
- [x] Virality scoring (predict clip engagement before posting) — DONE (iteration 8)
- [x] Shoppable content integration (product links in video descriptions) — DONE (iteration 15, affiliate links MVP)
- [x] Multi-platform export optimizer (platform-specific aspect ratios and formats) — DONE (iteration 9)
- [ ] Multi-language dubbing (AI lip-sync for cross-language distribution)

## Planned — Low Priority
- [x] Plugin system for custom platform integrations — DONE (iteration 16, pluggy-based)
- [ ] Multi-language UI
- [x] Video analytics dashboard (views, engagement tracking) — DONE (iteration 16, video_analytics.py)
- [x] Auto-niche detection from trending topics — DONE (iteration 10)
- [x] Encrypt cache files containing account data at rest — DONE (iteration 15)
- [ ] Kubernetes Helm chart for scaled deployment
- [x] Predictive micro-trend detection for topic selection — DONE (iteration 15)
