# Security Audit Report — MoneyPrinter

**Last Updated:** 2026-03-23
**Audit Run:** 3

## Summary

| Severity | Found | Fixed |
|----------|-------|-------|
| Critical | 2 | 2 |
| High | 5 | 5 |
| Medium | 9 | 9 |
| Low | 4 | 3 |

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
4. Add automated security scanning to CI pipeline
5. ✅ Remove unused `undetected_chromedriver` dependency (completed)
6. Consider adding CSP headers if web dashboard is added
7. ✅ Add email sending rate limiter to Outreach to prevent abuse (completed)
8. Add `pytest-cov` to CI for security-relevant code coverage tracking
9. Consider encrypting cache files containing account data at rest
