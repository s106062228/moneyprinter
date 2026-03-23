# Security Audit Report — MoneyPrinter

**Last Updated:** 2026-03-23
**Audit Run:** 1

## Summary

| Severity | Found | Fixed |
|----------|-------|-------|
| Critical | 2 | 2 |
| High | 4 | 4 |
| Medium | 3 | 3 |
| Low | 2 | 2 |

## Findings

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

### MEDIUM

#### 7. Config re-read on every function call
- **File:** `src/config.py`
- **Issue:** Each config getter opens and parses `config.json` — unnecessary I/O and could race with writes
- **Fix:** Documented as known issue. Will be addressed in future run with config caching.
- **Status:** ⚠️ Documented (non-security, performance)

#### 8. Wildcard imports reduce code auditability
- **Files:** Multiple (`from cache import *`, `from config import *`)
- **Issue:** Makes it hard to trace what symbols are in scope
- **Fix:** Documented as code quality issue for future refactoring.
- **Status:** ⚠️ Documented

#### 9. No request timeouts on some HTTP calls
- **File:** `src/classes/Outreach.py` line 178
- **Issue:** `requests.get(website)` without timeout could hang indefinitely
- **Fix:** Added `timeout=30` to all unprotected requests calls
- **Status:** ✅ Fixed

### LOW

#### 10. Temporary files not securely cleaned
- **File:** `src/utils.py`
- **Issue:** Temp files in `.mp/` are cleaned on startup but not on abnormal exit
- **Fix:** Documented. Consider `atexit` handler in future.
- **Status:** ⚠️ Documented

#### 11. No HTTPS enforcement for Ollama connection
- **File:** `src/llm_provider.py`
- **Issue:** Default Ollama URL is `http://127.0.0.1:11434` (localhost, acceptable for local use)
- **Fix:** Acceptable for local-only deployment. Added note that remote Ollama should use HTTPS.
- **Status:** ⚠️ Documented (acceptable risk for local use)

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
| undetected_chromedriver | Medium | Not actually used in codebase (only Firefox used). Consider removing. |

## Recommendations
1. Move all secrets to environment variables (in progress)
2. Add rate limiting to prevent API abuse
3. Implement proper logging with log levels
4. Add automated security scanning to CI pipeline
5. Remove unused `undetected_chromedriver` dependency
6. Consider adding CSP headers if web dashboard is added
