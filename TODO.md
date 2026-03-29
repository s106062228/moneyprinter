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

## Planned — High Priority
- [x] Content calendar UI (frontend for content scheduler) — DONE (iteration 7)
- [x] Dashboard frontend polish (charts, job management, content calendar view) — DONE (iteration 7)

## Planned — Medium Priority
- [x] Video template system (custom intros/outros) — DONE (iteration 9)
- [x] A/B testing for video titles and thumbnails — DONE (iteration 8)
- [x] AI hook optimization (trending hooks for better engagement) — DONE (iteration 9)
- [x] Auto-caption styling (animated captions like CapCut) — DONE (iteration 10)
- [x] Virality scoring (predict clip engagement before posting) — DONE (iteration 8)
- [ ] Shoppable content integration (product links in video descriptions)
- [x] Multi-platform export optimizer (platform-specific aspect ratios and formats) — DONE (iteration 9)
- [ ] Multi-language dubbing (AI lip-sync for cross-language distribution)

## Planned — Low Priority
- [ ] Plugin system for custom platform integrations
- [ ] Multi-language UI
- [ ] Video analytics dashboard (views, engagement tracking)
- [x] Auto-niche detection from trending topics — DONE (iteration 10)
- [ ] Encrypt cache files containing account data at rest
- [ ] Kubernetes Helm chart for scaled deployment
- [ ] Predictive micro-trend detection for topic selection
