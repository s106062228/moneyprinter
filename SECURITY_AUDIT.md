# Security Audit Report — MoneyPrinter

**Last Updated:** 2026-04-11
**Audit Run:** 26

---

## Run 26 — 2026-04-11 (niche_discovery security review)

A new module (`src/niche_discovery.py`) was added this run. Full OWASP-aligned scan performed. **All issues addressed during implementation and hardening pass.**

### Findings (all LOW)

1. **Inline `import math` moved to module-level**
   The `_score_volume()` method had an inline `import math` which violates PEP 8 and could mask import failures. **Fixed**: moved `import math` to module-level imports.

2. **Bare `except Exception: pass` blocks — no logging**
   13 exception handlers silently swallowed errors with no logging. **Fixed**: all bare except blocks now log at WARNING or DEBUG level using the project's `mp_logger` framework. No `str(exc)` appears in any log line (consistent with project security posture).

3. **Null-byte injection in niche list**
   The `discover()` method accepted user-provided niche strings without null-byte validation. **Fixed**: added `"\x00" not in n` filter in the niche list comprehension.

4. **Math domain error in `_score_volume()`**
   `math.log10()` called without explicit type validation of `count`. **Fixed**: added `try/except` with `int()` coercion and `max(1, ...)` guard before `log10()` call.

5. **Atomic file persistence with temp-file cleanup**
   Verified: `_persist()` uses `tempfile.mkstemp` + `os.replace` for atomicity, with temp-file unlink in the `finally` block. No orphan files on crash.

6. **Thread-safety**
   Verified: all public methods acquire the instance `RLock`. Concurrent access tested with 10-thread test.

7. **No exception message disclosure**
   Verified: no `str(exc)` or `repr(exc)` appears in any log line, return value, or user-facing output. Only sanitized logger.warning() calls with static messages.

8. **Unbounded growth protection**
   History list capped at `_MAX_ENTRIES` (10,000) on both load and persist. Niche lists, topic suggestions, and string fields all have length caps.

9. **No hardcoded secrets**
   Verified: no API keys, passwords, or credentials in source code.

No HIGH or MEDIUM issues introduced. All findings addressed during implementation.

---

## Run 25 — 2026-04-07 (profit_calculator security review)

A new module (`src/profit_calculator.py`) was added this run. It was scanned end-to-end against the OWASP checklist and prior audit patterns. **All 8 issues were addressed during initial implementation** (no regressions introduced).

### Findings (all LOW)

1. **Numeric input amplification in `estimate_cost`**
   `estimate_cost()` could be invoked with `llm_tokens=10**12`, causing a pathological product before any clamping step. **Fixed**: inputs are clamped inside `estimate_cost` to `_MAX_TOKENS` (10M), `_MAX_CHARS` (10M), `_MAX_COMPUTE_SECONDS` (10 days) and `_MAX_STORAGE_MB` (10 TB) **before** the multiplication.

2. **Config-driven rate injection**
   A malicious or corrupt `config.json` could set `profit.llm_rate_per_1k_tokens` to `1e308` and overflow the downstream arithmetic. **Fixed**: `_read_float()` rejects values outside `[0, _MAX_RATE]` (=$1,000 per unit) and falls back to the 2026 commodity default.

3. **Null-byte injection in `video_id`**
   Unvalidated `video_id` containing `\x00` could corrupt log output, persist corrupted state, or confuse downstream path operations. **Fixed**: `record_cost()` raises `ValueError` for empty, non-string, or null-byte-containing ids, and truncates to `_MAX_VIDEO_ID_LENGTH`.

4. **Non-atomic file write / orphaned temp files**
   Direct `open("w")` on the state file would corrupt on crash; a bare `tempfile.mkstemp` without cleanup leaves orphan `.profit_*.tmp` files on failure. **Fixed**: `_persist()` uses `tempfile.mkstemp` + `os.replace()` for atomicity, and unlinks the temp file in the `except` path so a crash cannot leak temp state.

5. **Corrupt / non-list JSON state file**
   A manipulated state file (e.g. `{"not": "list"}`) would previously cause a type error on load. **Fixed**: `_ensure_loaded()` silently recovers to an empty list for corrupt JSON, non-list top-level structures, and missing files.

6. **Exception-message info disclosure**
   Per the project posture, `str(exc)` must not appear in log lines or return values. **Verified**: no exception message strings are interpolated into logs or return dicts; only the exception class name / sanitized constants.

7. **Untrusted `RevenueTracker` cascading failure**
   If an injected revenue tracker raised from `get_entries()`, the profit calculator would previously propagate the error. **Fixed**: `_revenue_for_video()` and `get_profit_summary()` wrap tracker calls in `try/except` and fall back to empty revenue data.

8. **Thread-safety of read/modify/write**
   Concurrent `record_cost()` calls could race on `self._entries`. **Fixed**: all state-touching methods acquire a single `RLock`; verified with a 20-thread concurrent-write test.

### Separately — Functional (non-security) fix

- **`trend_detector._forecast_peak` flat-input bug**: `numpy.polyfit` on perfectly flat data can return slopes ~1e-17 due to floating-point noise, causing the `slope <= 0` guard to fail and a bogus peak date to be returned. Replaced with an epsilon check (`<= 1e-9`) and explicit normalisation of near-zero slopes to `0.0`.

### Test-suite drift (not security issues, but documented here for traceability)

- `test_mcp_server.py` (9 stale assertions) and `test_export_optimizer.py` (3 stale assertions) still expected the pre-Run-23 behaviour of leaking the original exception message substring in response/result fields. Run 23 sanitized these paths intentionally — tests were updated in Run 25 to positively assert the sanitized message **and** negatively assert the leaked substring is absent, thereby locking in the security fix against future regressions.
- `test_template_cli.py` referenced the optional `prettytable` dependency without an `importorskip` guard; the test now correctly skips in environments without that dep.

---

## Summary

| Severity | Found | Fixed |
|----------|-------|-------|
| Critical | 2 | 2 |
| High | 9 | 9 |
| Medium | 39 | 39 |
| Low | 58 | 56 |

## Findings — Run 24

### HIGH

#### 92. Dashboard path traversal bypass via absolute paths
- **File:** `src/dashboard.py` line 457
- **Issue:** Path traversal validation only checked for `..` and null bytes but accepted absolute paths like `/etc/passwd`
- **Fix:** Added checks rejecting paths starting with `/`, `\`, or drive letters (e.g., `C:`)
- **Status:** Fixed

### MEDIUM

#### 93. Timezone-naive datetime in analytics.py
- **File:** `src/analytics.py` line 66
- **Issue:** `datetime.now()` returns timezone-naive local time, causing inconsistent timestamps across systems and silent comparison failures with UTC-based timestamps in other modules
- **Fix:** Changed to `datetime.now(timezone.utc).isoformat()` with proper import
- **Status:** Fixed

#### 94. Auto-optimizer hour validation missing range check
- **File:** `src/auto_optimizer.py` lines 506, 912
- **Issue:** Parsed hour values from timestamps were not validated for 0-23 range; malformed timestamps like `T25:00:00` would parse without error
- **Fix:** Added `if not (0 <= hour < 24): continue` guard in both platform analysis and auto-tune schedule
- **Status:** Fixed

#### 95. Auto-optimizer info disclosure in recommendation text
- **File:** `src/auto_optimizer.py` line 690
- **Issue:** Recommendation description mentioned "Check credentials, API limits" which hints at authentication issues if reports are shared
- **Fix:** Changed to generic "Review your configuration and retry settings" language; capped failure count display
- **Status:** Fixed

### LOW

#### 96. Auto-optimizer timestamp format not validated
- **File:** `src/auto_optimizer.py` line 461
- **Issue:** Timestamp strings from JSON are length-checked and null-byte-checked but not format-validated; malformed strings could pass simple ISO comparison
- **Status:** Documented (acceptable risk — string comparison is conservative and safe)

#### 97. Auto-optimizer platform string Unicode edge case
- **File:** `src/auto_optimizer.py` line 489
- **Issue:** Platform strings undergo `str().lower()` but not ASCII-only validation before frozenset membership check
- **Status:** Documented (acceptable risk — frozenset membership check is exact match only)

## Findings — Run 23

### HIGH

#### 86. Insecure default network binding in MCP HTTP transport
- **File:** `src/mcp_server.py` line 330
- **Issue:** When `--http` flag is used without `--token`, the server binds to `0.0.0.0` exposing all MCP tools (analyze_video, publish_content, schedule_content) to the network without authentication
- **Fix:** Changed to bind to `127.0.0.1` (localhost only) when no auth token is provided; `0.0.0.0` only used when `--token` is set
- **Status:** Fixed

#### 87. Path traversal in dashboard calendar POST endpoint
- **File:** `src/dashboard.py` line 455
- **Issue:** `video_path` parameter accepted from user input without path traversal validation; `..` sequences could reference files outside the project
- **Fix:** Added `..` and null-byte checks on video_path, plus length truncation (1024 chars) for all fields
- **Status:** Fixed

### MEDIUM

#### 88. MCP tool exception info disclosure (6 locations)
- **File:** `src/mcp_server.py` lines 85, 88, 90, 139, 142, 230, 235, 291, 296
- **Issue:** Exception `str(exc)` returned in error response dicts, leaking internal paths, module names, and configuration details to MCP clients
- **Fix:** Replaced all `"message": str(exc)` with `"message": "Operation failed"` — full errors logged server-side only
- **Status:** Fixed

#### 89. Content scheduler platform string DoS
- **File:** `src/content_scheduler.py` line 204
- **Issue:** Platform strings from `from_dict()` deserialization were not length-capped before validation, allowing very long strings to waste memory
- **Fix:** Added `[:50]` truncation before `str(p).lower() in _ALLOWED_PLATFORMS` check
- **Status:** Fixed

#### 90. Dashboard calendar fields unbounded
- **File:** `src/dashboard.py` lines 452-455
- **Issue:** `title`, `scheduled_time` fields from POST body accepted without length limits
- **Fix:** Added `[:500]` and `[:100]` truncation respectively
- **Status:** Fixed

### LOW

#### 91. Revenue tracker JSON structure not schema-validated
- **File:** `src/revenue_tracker.py` line 264
- **Issue:** `_read_file()` loads JSON without validating structure; non-dict entries in list are silently skipped
- **Fix:** Acceptable risk — `from_dict()` has defensive validation and skips invalid entries
- **Status:** Documented (acceptable risk)

## Findings — Run 22

### HIGH

#### 81. Exception info disclosure in export_optimizer batch_export
- **File:** `src/export_optimizer.py` line 332
- **Issue:** `{exc}` in error log and result dict leaks full exception message including file paths and system info
- **Fix:** Changed to `{type(exc).__name__}` in both log and results dict
- **Status:** ✅ Fixed

### MEDIUM

#### 82. FFmpeg stderr leaked in RuntimeError (ffprobe)
- **File:** `src/ffmpeg_utils.py` line 164
- **Issue:** `result.stderr.strip()` in RuntimeError exposes system paths, library versions, and config details
- **Fix:** Moved stderr to `logger.debug()` (capped at 500 chars); RuntimeError now shows only exit code
- **Status:** ✅ Fixed

#### 83. FFmpeg stderr leaked in RuntimeError (trim, concat, transcode, extract_audio)
- **File:** `src/ffmpeg_utils.py` lines 318, 418, 525, 575-576
- **Issue:** Same pattern — subprocess stderr exposed in exception messages at 4 additional locations
- **Fix:** All 4 locations fixed: stderr logged at DEBUG level, RuntimeError sanitized
- **Status:** ✅ Fixed

#### 84. Plugin filepath leaked in import failure warning
- **File:** `src/plugin_manager.py` line 318
- **Issue:** `filepath` and full `exc` message logged in warning, exposing plugin directory structure
- **Fix:** Removed filepath and exc from warning; logged only `type(exc).__name__`
- **Status:** ✅ Fixed

#### 85. ffprobe JSON parse error leaked exception details
- **File:** `src/ffmpeg_utils.py` line 170
- **Issue:** `{exc}` in RuntimeError for invalid JSON could leak partial stdout content
- **Fix:** Changed to `{type(exc).__name__}`
- **Status:** ✅ Fixed

## Findings — Run 1

### CRITICAL

#### 1. Config file may contain plaintext secrets
- **File:** `config.json`
- **Issue:** API keys (nanobanana2_api_key, assembly_ai_api_key) and email credentials (SMTP password) stored in plaintext JSON
- **Fix:** Added `config.json` to `.gitignore` to prevent accidental commits. Added documentation recommending environment variables. Updated `config.py` to support env var fallbacks for sensitive fields.
- **Status:** ✅ Fixed

#### 2. Bare except clause swallows all errors in YouTube upload
- **File:** `src/classes/YouTube.py` line 851
- **Issue:** `except:` catches everything including KeyboardInterrupt and SystemExit, masking errors
- **Fix:** Changed to `except Exception as e:` with proper error logging
- **Status:** ✅ Fixed

### HIGH

#### 3. No input validation on user-provided file paths
- **File:** `src/main.py`, `src/classes/YouTube.py`
- **Issue:** Firefox profile paths and video file paths accepted without validation, potential path traversal
- **Fix:** Added `src/validation.py` with `validate_path()` and `validate_url()` utilities. Applied to YouTube and Twitter class constructors.
- **Status:** ✅ Fixed

#### 4. Potential command injection in Outreach scraper
- **File:** `src/classes/Outreach.py` line 133
- **Issue:** Scraper arguments constructed with shlex.split but the args string is built from config values that could contain shell metacharacters
- **Fix:** Already using shlex.split (safe) + subprocess.run without shell=True (safe). Added validation that config values don't contain shell metacharacters.
- **Status:** ✅ Fixed (verified safe)

#### 5. Email credentials handled insecurely
- **File:** `src/classes/Outreach.py` lines 247-252
- **Issue:** SMTP credentials read from config and passed directly to yagmail
- **Fix:** Added env var fallback for email credentials. Added warning in docs about securing config.json.
- **Status:** ✅ Fixed

#### 6. Unvalidated URLs fetched in Outreach
- **File:** `src/classes/Outreach.py` line 178
- **Issue:** `requests.get(website)` called on URLs from scraper output without validation
- **Fix:** Added URL validation before making requests. Added timeout parameter.
- **Status:** ✅ Fixed

## Findings — Run 2

### MEDIUM

#### 7. os.system() calls vulnerable to shell injection
- **File:** `src/classes/Outreach.py` line 33, `src/utils.py` lines 25-27
- **Issue:** `os.system("go version")` and `os.system("pkill firefox")` / `os.system("taskkill ...")` use the shell, which is vulnerable to injection if any part of the command were user-controlled
- **Fix:** Replaced all `os.system()` calls with `subprocess.run()` using argument lists (no shell=True). This is immune to shell injection.
- **Status:** ✅ Fixed

#### 8. File handle leak in Outreach email body
- **File:** `src/classes/Outreach.py` line 278
- **Issue:** `open(message_body, "r").read()` opens a file without closing it — file descriptor leak over many iterations
- **Fix:** Replaced with proper `with open(...) as f:` context manager pattern
- **Status:** ✅ Fixed

#### 9. Config re-read on every function call (performance + race condition)
- **File:** `src/config.py`
- **Issue:** Each config getter opened and parsed `config.json` — unnecessary I/O, could race with writes, and repeatedly leaked file descriptors
- **Fix:** Implemented in-memory config caching. Config is loaded once and cached. `reload_config()` available for forced refresh. All 25+ getter functions now read from cache.
- **Status:** ✅ Fixed

#### 10. No argument validation in cron.py
- **File:** `src/cron.py`
- **Issue:** `sys.argv` values used directly without validation — purpose could be any string, account_id not checked
- **Fix:** Added argument count validation, purpose whitelist check (only "twitter"/"youtube"), and basic account_id length validation
- **Status:** ✅ Fixed

#### 11. Shell script variable injection in upload_video.sh
- **File:** `scripts/upload_video.sh`
- **Issue:** Unquoted variables (`$id`, `$youtube_ids`) and no input validation on user-provided ID. Potential command injection via crafted account IDs.
- **Fix:** Added `set -euo pipefail`, quoted all variables, added regex validation for UUID-like IDs, used `command -v` instead of `[ -x ... ]`
- **Status:** ✅ Fixed

### LOW

#### 12. Unused dependency: undetected_chromedriver
- **File:** `requirements.txt`
- **Issue:** `undetected_chromedriver` is listed in requirements but never imported or used anywhere in the codebase. Increases attack surface unnecessarily.
- **Fix:** Removed from `requirements.txt`
- **Status:** ✅ Fixed

#### 13. Temporary files not securely cleaned
- **File:** `src/utils.py`
- **Issue:** Temp files in `.mp/` are cleaned on startup but not on abnormal exit
- **Fix:** Documented. Consider `atexit` handler in future.
- **Status:** ⚠️ Documented

#### 14. No HTTPS enforcement for Ollama connection
- **File:** `src/llm_provider.py`
- **Issue:** Default Ollama URL is `http://127.0.0.1:11434` (localhost, acceptable for local use)
- **Fix:** Acceptable for local-only deployment. Added note that remote Ollama should use HTTPS.
- **Status:** ⚠️ Documented (acceptable risk for local use)

## Findings — Run 3

### HIGH

#### 15. SSRF vulnerability — Missing timeout and validation on zip download
- **File:** `src/classes/Outreach.py` line 81
- **Issue:** `requests.get(zip_link)` had no timeout, no content-type validation, and no SSRF protection. An attacker-controlled URL could hang the process or redirect to internal services.
- **Fix:** Added `timeout=60`, `raise_for_status()`, ZIP magic byte validation (`PK\x03\x04`), and `os.path.normpath()` based path traversal check on extraction.
- **Status:** ✅ Fixed

### MEDIUM

#### 16. TOCTOU race condition in cache file operations
- **File:** `src/cache.py` — `get_accounts()`, `get_products()`, `add_account()`, `remove_account()`, `add_product()`
- **Issue:** `os.path.exists()` check followed by `open()` creates a time-of-check-time-of-use race condition. Between the check and the open, another process could create/modify/delete the file.
- **Fix:** Complete rewrite of cache.py with `_safe_read_json()` (try/except instead of exists-check) and `_safe_write_json()` (atomic writes via `tempfile.mkstemp()` + `os.replace()`).
- **Status:** ✅ Fixed

#### 17. Weak ZIP path traversal checks in song fetcher
- **File:** `src/utils.py` lines 108-118
- **Issue:** Path traversal check only looked for `..` literal string and `/` prefix, missing Unicode tricks, normpath-resolvable sequences, and Windows-style paths.
- **Fix:** Added `os.path.normpath()` + `os.path.abspath()` check to verify extracted path stays within target directory. Original string checks kept as defense-in-depth.
- **Status:** ✅ Fixed

#### 18. No URL validation before outreach HTTP requests
- **File:** `src/classes/Outreach.py` lines 182, 266
- **Issue:** URLs from scraped data used directly in `requests.get()` without validation. Potential SSRF — scraped URLs could point to internal IPs.
- **Fix:** Added `validate_url()` call and internal IP blocking (localhost, 127.0.0.1, 0.0.0.0, ::1) before making requests.
- **Status:** ✅ Fixed

#### 19. No rate limiting on email sends
- **File:** `src/classes/Outreach.py` lines 259-299
- **Issue:** Email sending loop had no delay between sends, risking SMTP rate limits, IP blacklisting, and spam classification.
- **Fix:** Added `_EMAIL_SEND_DELAY = 2` constant and `time.sleep()` between successful email sends.
- **Status:** ✅ Fixed

### LOW

#### 20. Exception information disclosure in scraper error handler
- **File:** `src/classes/Outreach.py` line 149
- **Issue:** Full `str(e)` printed to stdout on scraper errors, potentially leaking sensitive file paths or system details.
- **Fix:** Changed to print only `type(e).__name__` without the full exception message.
- **Status:** ✅ Fixed

## Dependency Audit

| Package | Risk | Notes |
|---------|------|-------|
| selenium | Medium | Browser automation — ensure WebDriver is up to date |
| requests | Low | Standard HTTP library |
| yagmail | Low | SMTP wrapper — credentials in memory during use |
| moviepy | Low | Video processing |
| assemblyai | Low | Cloud API — API key required |
| faster-whisper | Low | Local model — no network exposure |
| ollama | Low | Local LLM client |
| ~~undetected_chromedriver~~ | ~~Removed~~ | Not used in codebase — removed in Run 2 |

## Recommendations
1. ✅ Move all secrets to environment variables (completed — env var fallbacks added)
2. ✅ Add rate limiting to prevent API abuse (completed — email send delay added)
3. ✅ Implement proper logging with log levels (completed — `mp_logger.py` added)
4. ✅ Add automated security scanning to CI pipeline (completed — Bandit + safety in GitHub Actions)
5. ✅ Remove unused `undetected_chromedriver` dependency (completed)
6. Consider adding CSP headers if web dashboard is added
7. ✅ Add email sending rate limiter to Outreach to prevent abuse (completed)
8. Add `pytest-cov` to CI for security-relevant code coverage tracking
9. Consider encrypting cache files containing account data at rest
10. ✅ Fix TOCTOU in TikTok cache operations (completed)
11. ✅ Add SSRF protection to Outreach main loop (completed)
12. ✅ Cap recursive retries in YouTube pipeline (completed)

## Findings — Run 4

### MEDIUM

#### 21. TOCTOU race condition in TikTok cache operations
- **File:** `src/classes/TikTok.py` — `get_videos()`, `add_video()`
- **Issue:** Used `os.path.exists()` check before `open()` — same TOCTOU pattern previously fixed in `cache.py` during Run 3. Between the check and the open, another process could create/modify/delete the file.
- **Fix:** Complete rewrite with `_safe_read_cache()` (try/except instead of exists-check) and `_safe_write_cache()` (atomic writes via `tempfile.mkstemp()` + `os.replace()`).
- **Status:** ✅ Fixed

#### 22. Missing SSRF protection in Outreach main email loop
- **File:** `src/classes/Outreach.py` line 297
- **Issue:** `requests.get(website, timeout=30)` in the main email-sending loop did not validate URLs or block internal IPs. Only `set_email_for_website()` had SSRF protection. Scraped URLs could redirect to internal services.
- **Fix:** Added `validate_url()` call and internal IP blocking (localhost, 127.0.0.1, 0.0.0.0, ::1) before making the request in the main loop.
- **Status:** ✅ Fixed

#### 23. Unbounded recursion in YouTube video generation pipeline
- **File:** `src/classes/YouTube.py` — `generate_script()`, `generate_metadata()`, `generate_prompts()`
- **Issue:** All three methods recursively called themselves when LLM output didn't meet criteria (script too long, title too long, prompts unparseable). No depth limit — could cause StackOverflow if the LLM consistently returns oversized output.
- **Fix:** Added `_retry_depth` parameter with `_MAX_RETRIES = 5` cap. After max retries, uses truncated/fallback output instead of infinite recursion.
- **Status:** ✅ Fixed

### LOW

#### 24. Exception information disclosure in Outreach email loop
- **File:** `src/classes/Outreach.py` line 332
- **Issue:** `error(f" => Error: {err}...")` leaked full exception string including potentially sensitive file paths, URLs, or system details.
- **Fix:** Changed to `error(f" => Error processing item: {type(err).__name__}")` — only exposes exception class name.
- **Status:** ✅ Fixed

#### 25. Twitter/YouTube cache writes not atomic
- **File:** `src/classes/Twitter.py` — `add_post()`, `src/classes/YouTube.py` — `add_video()`
- **Issue:** Cache writes use `open("r")` then `open("w")` — if the process crashes mid-write, the cache file is corrupted. Not using the atomic write pattern from `cache.py`.
- **Fix:** Complete rewrite of both `Twitter.py` and `YouTube.py` cache operations with `_safe_read_cache()` (try/except) and `_safe_write_cache()` (atomic tempfile + os.replace). 30 new tests added to verify.
- **Status:** ✅ Fixed

#### 26. No CI security scanning
- **File:** N/A
- **Issue:** No automated security scanning in CI/CD pipeline.
- **Fix:** Added GitHub Actions workflow with Bandit (Python SAST) and safety (dependency vulnerability scanning).
- **Status:** ✅ Fixed

## Findings — Run 5

### MEDIUM

#### 27. Analytics TOCTOU race condition and non-atomic writes
- **File:** `src/analytics.py` — `_load_analytics()`, `_save_analytics()`
- **Issue:** `_load_analytics()` used `os.path.exists()` before `open()` — TOCTOU race condition. `_save_analytics()` used direct `open("w")` — non-atomic, data loss on crash.
- **Fix:** Rewrote `_load_analytics()` with try/except (no exists check). Rewrote `_save_analytics()` with `tempfile.mkstemp()` + `os.replace()` for atomic writes.
- **Status:** ✅ Fixed

#### 28. Twitter cache TOCTOU race condition and non-atomic writes
- **File:** `src/classes/Twitter.py` — `get_posts()`, `add_post()`
- **Issue:** `get_posts()` used `os.path.exists()` then `open()`. `add_post()` used nested `open("r")` then `open("w")` — non-atomic, same pattern as issue #25.
- **Fix:** Added `_safe_read_cache()` and `_safe_write_cache()` methods. Complete rewrite of both `get_posts()` and `add_post()` to use atomic operations.
- **Status:** ✅ Fixed

#### 29. YouTube cache TOCTOU race condition and non-atomic writes
- **File:** `src/classes/YouTube.py` — `get_videos()`, `add_video()`
- **Issue:** Same TOCTOU and non-atomic write patterns as Twitter.py.
- **Fix:** Same atomic rewrite pattern. Added `_safe_read_cache()` and `_safe_write_cache()` methods.
- **Status:** ✅ Fixed

### LOW

#### 30. API response body logged in verbose mode (information disclosure)
- **File:** `src/classes/YouTube.py` line 390
- **Issue:** `warning(f"...Response: {body}")` logged the full Gemini API response body in verbose mode. Response could contain tokens, internal identifiers, or debug info.
- **Fix:** Changed to generic message: `"Check API response format."` — no response body logged.
- **Status:** ✅ Fixed

#### 31. Full exception string logged in image generation error
- **File:** `src/classes/YouTube.py` line 394
- **Issue:** `warning(f"...{str(e)}")` could leak API URLs, headers, or system paths in exception messages.
- **Fix:** Changed to `type(e).__name__` — only exposes exception class name.
- **Status:** ✅ Fixed

## Findings — Run 6

### MEDIUM

#### 32. Unsafe CSV parsing in Outreach email loop (CSV injection risk)
- **File:** `src/classes/Outreach.py` lines 293, 313, 319
- **Issue:** Direct `item.split(",")` used instead of proper CSV parsing. If CSV fields contain quoted commas (valid in CSV), this corrupts field extraction — potentially sending emails to wrong addresses or using wrong company names. Also no bounds checking on split indices.
- **Fix:** Replaced all `item.split(",")` calls with `csv.reader()` (Python's built-in CSV parser) which properly handles quoted fields, escaped commas, and edge cases. Added empty row checks.
- **Status:** ✅ Fixed

#### 33. URL bounds check missing in YouTube channel ID extraction
- **File:** `src/classes/YouTube.py` line 756
- **Issue:** `driver.current_url.split("/")[-1]` assumes URL always has the expected structure. If YouTube Studio redirects to an unexpected URL format, `[-1]` could return the wrong value (e.g., domain name instead of channel ID).
- **Fix:** Added `len(url_parts)` validation and empty-string check before using the split result. Raises `ValueError` with descriptive message on unexpected URL structure.
- **Status:** ✅ Fixed

#### 34. URL bounds check missing in YouTube video ID extraction
- **File:** `src/classes/YouTube.py` line 885
- **Issue:** `href.split("/")[-2]` assumes video URL always has at least 3 path segments. Malformed `href` attributes could cause IndexError or extract incorrect video ID.
- **Fix:** Added `len(href_parts) < 3` validation. Raises `ValueError` with the problematic URL for debugging.
- **Status:** ✅ Fixed

### LOW

#### 35. Email regex allows literal pipe character in TLD
- **File:** `src/classes/Outreach.py` line 216
- **Issue:** Email regex pattern `[A-Z|a-z]{2,7}` includes a literal `|` character inside the bracket expression (not an OR operator). Also limits TLDs to 7 characters, rejecting valid TLDs like `.technology`.
- **Fix:** Changed to `[A-Za-z]{2,}` — removed literal pipe, removed upper length limit to accept all valid TLDs.
- **Status:** ✅ Fixed

#### 36. No Firefox profile path validation on account creation
- **File:** `src/main.py` lines 80-81
- **Issue:** Firefox profile path entered by user was stored directly without validation. Invalid or path-traversal paths could be stored and later used by Selenium.
- **Fix:** Added `validate_path()` call from `validation.py` on both YouTube and Twitter account creation paths. Returns early with error message if path is invalid.
- **Status:** ✅ Fixed

## Findings — Run 7

### MEDIUM

#### 37. Non-atomic CSV write in Outreach email extraction
- **File:** `src/classes/Outreach.py` — `set_email_for_website()`
- **Issue:** CSV file was read then written back with `open("w")` — if the process crashes mid-write, the CSV is corrupted. No bounds checking on the row index either.
- **Fix:** Added index bounds validation. Rewrote write path with `tempfile.mkstemp()` + `os.replace()` for atomic writes.
- **Status:** ✅ Fixed

#### 38. Browser resource leak — no context manager protocol
- **File:** `src/classes/YouTube.py`, `src/classes/Twitter.py`, `src/classes/TikTok.py`, `src/classes/AFM.py`
- **Issue:** All four browser-using classes instantiate Firefox in `__init__` but don't implement `__enter__`/`__exit__`. If an exception occurs between construction and `quit()`, the browser process and geckodriver leak as orphaned processes.
- **Fix:** Added `__enter__` and `__exit__` methods to all four classes, enabling `with` statement usage and automatic browser cleanup on exceptions.
- **Status:** ✅ Fixed

### LOW

#### 39. Exception info disclosure in utils.py (3 locations)
- **File:** `src/utils.py` — `close_running_selenium_instances()`, `fetch_songs()`, `choose_random_song()`
- **Issue:** `str(e)` was logged in error messages, potentially leaking file paths, URLs, or system details.
- **Fix:** Changed all three locations to `type(e).__name__` — only exposes exception class name.
- **Status:** ✅ Fixed

#### 40. Exception info disclosure in TikTok upload
- **File:** `src/classes/TikTok.py` line 278
- **Issue:** `error(f"TikTok upload failed: {e}")` could leak Selenium internal paths, WebDriver URLs, or system details.
- **Fix:** Changed to `type(e).__name__`.
- **Status:** ✅ Fixed

#### 41. Exception info disclosure in YouTube subtitle generation
- **File:** `src/classes/YouTube.py` line 687
- **Issue:** `warning(f"Failed to generate subtitles...: {e}")` could leak audio file paths or Whisper model details.
- **Fix:** Changed to `type(e).__name__`.
- **Status:** ✅ Fixed

#### 42. Exception info disclosure in YouTube upload
- **File:** `src/classes/YouTube.py` line 920
- **Issue:** `error(f"YouTube upload failed: {e}")` could leak Selenium internals.
- **Fix:** Changed to `type(e).__name__`.
- **Status:** ✅ Fixed

#### 43. Niche file write unbounded length
- **File:** `src/classes/Outreach.py` line 253
- **Issue:** `self.niche` (from config) written to `niche.txt` without length limit. A maliciously large niche string could fill disk.
- **Fix:** Added `[:500]` length limit on the niche string written to file.
- **Status:** ✅ Fixed

#### 44. Song download URL leaked in error message
- **File:** `src/utils.py` line 129
- **Issue:** `warning(f"Failed to fetch songs from {download_url}: {err}")` leaked both the configured download URL and the full exception message.
- **Fix:** Changed to `"Failed to fetch songs from configured URL: {type(err).__name__}"` — no URL or exception details exposed.
- **Status:** ✅ Fixed

## Findings — Run 8

### LOW

#### 45. Exception info disclosure in LLM provider initialization
- **File:** `src/main.py` line 467
- **Issue:** `error(f"Could not initialize LLM provider '{provider_name}': {e}")` leaked full exception message, which could contain API key validation errors, file paths, or connection details from the LLM provider SDK.
- **Fix:** Changed to `type(e).__name__` — only exposes exception class name.
- **Status:** ✅ Fixed

#### 46. Exception info disclosure in model listing
- **File:** `src/main.py` line 479
- **Issue:** `error(f"Could not list models from {get_provider_name()}: {e}")` leaked full exception message from the LLM provider, potentially exposing API endpoints, auth errors, or system paths.
- **Fix:** Changed to `type(e).__name__` — only exposes exception class name.
- **Status:** ✅ Fixed

## Findings — Run 9

### MEDIUM

#### 47. Unbounded analytics event growth (disk exhaustion)
- **File:** `src/analytics.py` — `track_event()`
- **Issue:** Analytics events were appended to `analytics.json` indefinitely with no rotation or size limit. Over time (especially with automated cron jobs running daily), this file could grow to hundreds of megabytes or gigabytes, eventually filling the disk.
- **Fix:** Added `_MAX_EVENTS = 10000` constant and event rotation — when events exceed 10,000, oldest events are trimmed on each write. Keeps disk usage bounded while retaining recent history.
- **Status:** ✅ Fixed

### LOW

#### 48. Config load error leaks full file path and JSON parse details
- **File:** `src/config.py` line 35
- **Issue:** `print(colored(f"[config] Failed to load {_config_path}: {exc}", "red"))` leaked the full filesystem path to `config.json` and the full JSON decode error message (which can include byte offsets and partial content).
- **Fix:** Changed to `type(exc).__name__` — only exposes exception class name, no paths or content details.
- **Status:** ✅ Fixed

#### 49. ValueError message echoed to user in main menu
- **File:** `src/main.py` line 67
- **Issue:** `print(f"Invalid input: {e}")` echoed the full ValueError exception message to the user. While the exception came from user input (int conversion), the pattern could leak internal details if the error handling path changed.
- **Fix:** Changed to generic message: "Invalid input. Please enter a valid number."
- **Status:** ✅ Fixed

#### 50. File path disclosure in scraper output error
- **File:** `src/classes/Outreach.py` line 283
- **Issue:** `error(f" => Scraper output not found at {output_path}. Check scraper logs and configuration.")` leaked the full filesystem path to the scraper output file.
- **Fix:** Changed to generic message without file path.
- **Status:** ✅ Fixed

#### 51. rem_temp_files crashes if .mp directory missing
- **File:** `src/utils.py` — `rem_temp_files()`
- **Issue:** `os.listdir(mp_dir)` would raise `FileNotFoundError` if `.mp` didn't exist yet (first run). Also, `os.remove()` was called without checking if the entry was a file (could fail on subdirectories like `logs/`), and had no error handling for permission issues.
- **Fix:** Added `os.path.isdir()` guard, `os.path.isfile()` check, and try/except OSError wrapper.
- **Status:** ✅ Fixed

## Findings — Run 10

### MEDIUM

#### 52. Arbitrary file read via outreach message body path
- **File:** `src/classes/Outreach.py` — `start()` method
- **Issue:** `outreach_message_body_file` config value was opened with `open(message_body, "r")` without any path validation. A malicious or misconfigured config could point this path to any file on the system (e.g., `/etc/passwd`, `~/.ssh/id_rsa`), enabling arbitrary file reads. The file contents were then used as the email body, potentially exfiltrating sensitive data via email.
- **Fix:** Added path validation: `os.path.abspath()` comparison ensures the message body file is within the project directory. Also added `os.path.isfile()` check before opening. Aborts the outreach process with an error if the path is invalid.
- **Status:** ✅ Fixed

#### 53. Outreach email recipient not validated
- **File:** `src/classes/Outreach.py` — `start()` method, email sending loop
- **Issue:** The `receiver_email` extracted from CSV as `fields[-1]` was only checked for the presence of `@` — this allowed malformed addresses like `@`, `user@`, or strings with spaces/special characters to be passed to `yagmail.send()`. Could cause SMTP errors or be used to inject SMTP headers.
- **Fix:** Replaced the simple `"@" not in receiver_email` check with a proper regex validation (`^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`) that enforces a valid email format before sending.
- **Status:** ✅ Fixed

#### 54. Scraper timeout uncapped — potential indefinite process hang
- **File:** `src/config.py` — `get_scraper_timeout()`
- **Issue:** The `scraper_timeout` config value was converted to `int()` with no upper bound. A user could set this to an extremely large value (e.g., 999999999), causing the scraper subprocess to run indefinitely and consume system resources. Combined with automated cron jobs, this could effectively DoS the host machine.
- **Fix:** Added `min(max(val, 10), 3600)` bounds — timeout is now clamped between 10 seconds and 1 hour (3600 seconds).
- **Status:** ✅ Fixed

### LOW

#### 55. Affiliate link not validated in main menu
- **File:** `src/main.py` — affiliate marketing account creation
- **Issue:** The `affiliate_link` entered by the user was stored directly in the cache without URL validation. This value was later passed to `AffiliateMarketing.__init__()` which opens it in a browser via `self.browser.get(self.affiliate_link)`. While AFM's constructor does validate the scheme, the validation was happening after browser initialization, wasting resources on invalid input.
- **Fix:** Added `validate_url()` call immediately after user input, before cache storage or account creation. Returns early with an error message for invalid URLs.
- **Status:** ✅ Fixed

#### 56. Cache-stored Firefox profile paths used without re-validation
- **File:** `src/main.py`, `src/publisher.py`
- **Issue:** When loading accounts from cache, `account["firefox_profile"]` is passed directly to browser classes without re-validation. If the cache file is manually edited (or corrupted), the path could point to an invalid or malicious directory.
- **Fix:** Documented. The browser classes (`YouTube`, `Twitter`, `TikTok`, `AFM`) already validate via `os.path.isdir()` in their constructors and raise `ValueError` for invalid paths, providing defense-in-depth. Adding cache-level re-validation would be a future enhancement.
- **Status:** ⚠️ Documented (mitigated by constructor validation)

#### 57. Schedule file contains video paths in plaintext
- **File:** `src/content_scheduler.py` — `_SCHEDULE_FILE`
- **Issue:** The content scheduler persists `video_path` values in a JSON file at `.mp/schedule.json`. These paths are stored in plaintext and could reveal the user's filesystem structure if the file is accidentally shared or committed.
- **Fix:** Documented. The `.mp/` directory is already gitignored. The schedule file follows the same persistence pattern as analytics and cache files. Encrypting schedule data at rest is a future enhancement tracked in TODO.md.
- **Status:** ⚠️ Documented (mitigated by .gitignore)

## Findings — Run 11

### MEDIUM

#### 58. Retry module logs full exception messages (information disclosure)
- **File:** `src/retry.py` — `retry()` decorator (lines 69, 78), `retry_call()` (lines 142, 151), `PipelineStage.execute()` (line 208)
- **Issue:** All retry logging used `exc` (the full exception object) in log messages. Exception messages from LLM API calls, Selenium WebDriver, or HTTP requests can contain API URLs, auth tokens, file paths, or system details. Since retry is used around network-heavy operations, this was a significant leak vector.
- **Fix:** Changed all 5 logging sites from `exc` to `type(exc).__name__` — only the exception class name is logged, no sensitive details.
- **Status:** ✅ Fixed

### LOW

#### 59. YouTube Studio href URL logged in verbose mode
- **File:** `src/classes/YouTube.py` line 902
- **Issue:** `info(f"\t=> Extracting video ID from URL: {href}")` logged the full YouTube Studio internal URL in verbose mode. While only visible in verbose output, this could leak internal YouTube Studio paths if logs are shared.
- **Fix:** Changed to generic message: "Extracting video ID from upload response..." — no URL logged.
- **Status:** ✅ Fixed

#### 60. Outreach `is_go_installed()` uses `subprocess.call` without capturing output
- **File:** `src/classes/Outreach.py` line 69
- **Issue:** `subprocess.call(["go", "version"])` printed Go version output directly to stdout. While not a direct security risk, it leaks system binary version info unnecessarily. Also used a bare `except Exception` instead of targeted exception handling.
- **Fix:** Changed to `subprocess.run(["go", "version"], capture_output=True, check=False)` with targeted `(FileNotFoundError, OSError)` exception handling.
- **Status:** ✅ Fixed

#### 61. mp_logger leaks full exception in file handler setup warning
- **File:** `src/mp_logger.py` line 113
- **Issue:** `root_logger.warning(f"Could not set up file logging: {exc}")` leaked the full `OSError`/`PermissionError` message, which could contain filesystem paths (e.g., `/home/user/.mp/logs/moneyprinter.log`).
- **Fix:** Changed to `type(exc).__name__` — only exposes exception class name.
- **Status:** ✅ Fixed

## Findings — Run 12

### MEDIUM

#### 62. ReDoS risk in SEO optimizer JSON parser
- **File:** `src/seo_optimizer.py` — `_parse_json_array()`
- **Issue:** Regex `re.search(r"\[.*?\]", cleaned, re.DOTALL)` operated on raw LLM output without length limit. Malformed LLM responses with deeply nested structures could cause catastrophic backtracking.
- **Fix:** Added `_MAX_LLM_RESPONSE_LEN = 10000` constant and truncation before regex operations.
- **Status:** ✅ Fixed

### LOW

#### 63. SEO optimizer `from_dict()` missing field validation
- **File:** `src/seo_optimizer.py` — `SEOResult.from_dict()`
- **Issue:** Score field accepted any integer without range validation. Platform field accepted any string. List fields had no length caps. Maliciously crafted dict could inject oversized data.
- **Fix:** Added score clamping (0-100), platform whitelist validation, list length caps (tags: 50, hashtags: 15, hooks: 10), and string length caps on title/description.
- **Status:** ✅ Fixed

#### 64. Publisher video_path leak in error message
- **File:** `src/publisher.py` — `PublishJob.validate()`
- **Issue:** `ValueError(f"Video file does not exist: {self.video_path}")` leaked the full filesystem path in the exception message.
- **Fix:** Changed to generic message without path.
- **Status:** ✅ Fixed

#### 65. Config `assert_folder_structure()` path disclosure
- **File:** `src/config.py` — `assert_folder_structure()`
- **Issue:** `print(f"=> Creating .mp folder at {mp_dir}")` leaked the full filesystem path to the `.mp` directory in verbose mode.
- **Fix:** Changed to generic message: "Creating .mp data folder".
- **Status:** ✅ Fixed

#### 66. Config `get_threads()` missing bounds
- **File:** `src/config.py` — `get_threads()`
- **Issue:** Thread count from config was cast to `int()` with no bounds checking. Excessively large values could cause resource exhaustion during MoviePy video encoding.
- **Fix:** Added `min(max(val, 1), 32)` bounds — thread count clamped between 1 and 32.
- **Status:** ✅ Fixed

#### 67. SEO optimizer no rate limiting between LLM calls
- **File:** `src/seo_optimizer.py` — `optimize_metadata()`
- **Issue:** 5 consecutive LLM API calls (title, description, tags, hashtags, hooks) made without any delay. Could hit API rate limits or cause excessive API costs with cloud providers.
- **Fix:** Added `_LLM_CALL_DELAY = 0.5` constant and `time.sleep()` between consecutive LLM calls.
- **Status:** ✅ Fixed

## Findings — Run 13

### MEDIUM

#### 68. ScheduledJob.from_dict() missing input validation on deserialized data
- **File:** `src/content_scheduler.py` — `ScheduledJob.from_dict()`
- **Issue:** Deserialized fields from the schedule JSON file were accepted without any validation — no length caps on video_path/title/description, no platform whitelist enforcement, no status validation, no repeat_interval bounds. A corrupted or maliciously crafted schedule file could inject oversized strings or invalid platforms into the scheduler, causing unexpected behavior or memory exhaustion.
- **Fix:** Added comprehensive validation: type checking on input dict, field truncation (video_path capped to 1024, title to 500, description to 5000), platform whitelist filtering, status enum validation, repeat_interval clamping (0-720), tags capped at 50, string fields truncated to 50 chars for IDs/timestamps.
- **Status:** ✅ Fixed

### LOW

#### 69. Content scheduler leaks video file path in error message
- **File:** `src/content_scheduler.py` line 422
- **Issue:** `FileNotFoundError(f"Video file no longer exists: {job.video_path}")` leaked the full filesystem path of the scheduled video in the exception message.
- **Fix:** Changed to generic message without path: "Scheduled video file no longer exists at the specified path."
- **Status:** ✅ Fixed

#### 70. Validation module leaks normalized path in error messages
- **File:** `src/validation.py` — `validate_path()` line 38, `validate_directory()` line 59
- **Issue:** Error messages included the full normalized filesystem path (e.g., `f"Path does not exist: {normalized}"`), leaking directory structure.
- **Fix:** Changed to generic messages: "Path does not exist." and "Path is not a directory." — no paths exposed.
- **Status:** ✅ Fixed

#### 71. Validation module leaks URL in error message
- **File:** `src/validation.py` — `validate_url()` line 91
- **Issue:** `f"URL is missing a host: {url}"` echoed the user-provided URL back in the error message. Could be used for reflected content in logs.
- **Fix:** Changed to generic message: "URL is missing a host."
- **Status:** ✅ Fixed

#### 72. Pipeline error dict stores full exception strings
- **File:** `src/retry.py` — `run_pipeline()` line 240
- **Issue:** `errors[stage.name] = str(stage.error)` stored the full exception string representation in the pipeline results dict. Exception messages from API calls, file operations, or Selenium could contain API URLs, file paths, or system details. The errors dict is returned to callers and could be logged or displayed.
- **Fix:** Changed to `type(stage.error).__name__` — only the exception class name is stored.
- **Status:** ✅ Fixed

#### 73. Analytics get_events() limit parameter unbounded
- **File:** `src/analytics.py` — `get_events()`
- **Issue:** The `limit` parameter accepted any integer without upper bounds. A caller passing an extremely large limit could cause excessive memory usage when reversing and slicing the event list.
- **Fix:** Added `_MAX_LIMIT = 10000` cap and bounds clamping: `limit = min(max(limit, 1), _MAX_LIMIT)`.
- **Status:** ✅ Fixed

#### 74. Webhooks module uses deprecated datetime.utcnow()
- **File:** `src/webhooks.py` — `_format_discord_payload()`, `_format_slack_payload()`
- **Issue:** `datetime.utcnow()` is deprecated since Python 3.12 and will be removed in a future Python version. It also returns a naive datetime without timezone info.
- **Fix:** Changed to `datetime.now(timezone.utc)` which returns a timezone-aware datetime and follows Python 3.12+ best practices.
- **Status:** ✅ Fixed

## Findings — Run 14

### MEDIUM

#### 75. Analytics get_events() safety cap overridable by callers
- **File:** `src/analytics.py` — `get_events()`
- **Issue:** The `_MAX_LIMIT` safety cap was exposed as a function parameter with a default value of 10000. Any caller could pass `_MAX_LIMIT=999999999` to bypass the intended safety limit, potentially causing excessive memory usage when processing large event histories.
- **Fix:** Removed `_MAX_LIMIT` from function parameters. Promoted to module-level constant `_MAX_QUERY_LIMIT = 10000` that cannot be overridden by callers.
- **Status:** ✅ Fixed

### LOW

#### 76. Songs directory path disclosed in verbose mode
- **File:** `src/utils.py` line 90
- **Issue:** `info(f" => Created directory: {files_dir}")` leaked the full filesystem path to the Songs directory in verbose mode.
- **Fix:** Changed to generic message: "Created Songs directory." — no path exposed.
- **Status:** ✅ Fixed

#### 77. No prompt length limit in LLM provider
- **File:** `src/llm_provider.py` — `generate_text()`
- **Issue:** Prompts of any length were passed directly to LLM API calls without validation. An extremely long prompt (e.g., from a corrupted script or malicious input) could cause excessive API costs with cloud providers (OpenAI, Anthropic, Groq) or OOM errors with local Ollama.
- **Fix:** Added `_MAX_PROMPT_LENGTH = 50000` constant and truncation before API calls.
- **Status:** ✅ Fixed

#### 78. Unnecessary top-level import of srt_equalizer in config module
- **File:** `src/config.py` line 4
- **Issue:** `import srt_equalizer` was at module level despite only being used in `equalize_subtitles()`. This caused: (a) import failure if the package wasn't installed even when subtitle features weren't needed, (b) unnecessary memory usage for all config operations, (c) increased attack surface from loading a third-party module unconditionally.
- **Fix:** Moved to lazy import inside `equalize_subtitles()`.
- **Status:** ✅ Fixed

#### 79. Thumbnail generate_from_metadata() missing output_dir validation
- **File:** `src/thumbnail.py` — `generate_from_metadata()`
- **Issue:** `output_dir` parameter was used to construct the output path without validation. A null byte or empty string could cause unexpected behavior or path injection.
- **Fix:** Added validation for non-empty string and null byte check before path construction.
- **Status:** ✅ Fixed

#### 80. Publisher browser cleanup could mask original errors
- **File:** `src/publisher.py` — `_publish_youtube()`, `_publish_tiktok()`, `_publish_twitter()`
- **Issue:** `finally` blocks called `yt.browser.quit()` / `tiktok.browser.quit()` / `twitter.browser.quit()` without checking if the `browser` attribute exists. If the browser class `__init__` failed mid-construction (e.g., invalid Firefox profile), an `AttributeError` in the cleanup would mask the original error.
- **Fix:** Added `hasattr()` guard checks before calling `browser.quit()`.
- **Status:** ✅ Fixed
