"""
SEO Optimizer for MoneyPrinter.

Optimizes video metadata (titles, descriptions, tags, hashtags) for maximum
discoverability across YouTube, TikTok, and Twitter. Uses the configured LLM
provider to generate SEO-optimized content following 2026 platform best practices.

Key features:
  - Platform-specific optimization (YouTube Shorts, TikTok, Twitter)
  - Keyword-first title generation with character limits
  - Structured description with hooks, timestamps, and CTAs
  - Hashtag strategy (primary + niche + trending format)
  - Tag generation for YouTube discovery
  - Engagement hook generation for first-frame retention
  - Input validation and safe defaults
"""

import json
import re
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from config import _get


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PLATFORM_LIMITS = {
    "youtube": {"title": 100, "description": 5000, "tags": 500, "hashtags": 15},
    "tiktok": {"title": 150, "description": 2200, "hashtags": 10},
    "twitter": {"title": 0, "description": 280, "hashtags": 5},
    "instagram": {"title": 0, "description": 2200, "hashtags": 30},
}

_SUPPORTED_PLATFORMS = frozenset(_PLATFORM_LIMITS.keys())

# Maximum input lengths to prevent abuse
_MAX_SUBJECT_LEN = 500
_MAX_SCRIPT_LEN = 10000
_MAX_NICHE_LEN = 200

# Rate limiting between consecutive LLM calls (seconds)
_LLM_CALL_DELAY = 0.5


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def get_seo_enabled() -> bool:
    """Check if SEO optimization is enabled in config."""
    seo_config = _get("seo", {})
    return bool(seo_config.get("enabled", True))


def get_seo_target_platforms() -> list[str]:
    """Get the list of platforms to optimize for."""
    seo_config = _get("seo", {})
    platforms = seo_config.get("platforms", ["youtube"])
    return [p.lower().strip() for p in platforms if p.lower().strip() in _SUPPORTED_PLATFORMS]


def get_seo_language() -> str:
    """Get the target language for SEO content."""
    seo_config = _get("seo", {})
    return seo_config.get("language", "en")


def get_seo_include_tags() -> bool:
    """Whether to generate tags (YouTube-specific)."""
    seo_config = _get("seo", {})
    return bool(seo_config.get("include_tags", True))


def get_seo_include_hooks() -> bool:
    """Whether to generate engagement hooks."""
    seo_config = _get("seo", {})
    return bool(seo_config.get("include_hooks", True))


def get_seo_hashtag_count() -> int:
    """Get the target number of hashtags to generate."""
    seo_config = _get("seo", {})
    count = int(seo_config.get("hashtag_count", 8))
    return min(max(count, 1), 15)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SEOResult:
    """Container for SEO-optimized metadata."""

    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    platform: str = "youtube"
    score: int = 0  # 0-100 estimated SEO quality score

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "hashtags": self.hashtags,
            "hooks": self.hooks,
            "platform": self.platform,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SEOResult":
        """Deserialize from dictionary."""
        if not isinstance(data, dict):
            raise ValueError("SEOResult.from_dict requires a dict")
        # Clamp score to valid range (0-100)
        raw_score = int(data.get("score", 0))
        clamped_score = min(max(raw_score, 0), 100)
        # Validate platform
        raw_platform = str(data.get("platform", "youtube"))
        safe_platform = raw_platform if raw_platform in _SUPPORTED_PLATFORMS else "youtube"
        return cls(
            title=str(data.get("title", ""))[:_MAX_SUBJECT_LEN],
            description=str(data.get("description", ""))[:_MAX_SCRIPT_LEN],
            tags=[str(t) for t in list(data.get("tags", []))[:50]],
            hashtags=[str(h) for h in list(data.get("hashtags", []))[:15]],
            hooks=[str(h) for h in list(data.get("hooks", []))[:10]],
            platform=safe_platform,
            score=clamped_score,
        )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_input(subject: str, script: str, niche: str, platform: str) -> None:
    """Validate inputs before processing."""
    if not subject or not subject.strip():
        raise ValueError("Subject cannot be empty")
    if "\x00" in subject or "\x00" in script or "\x00" in niche:
        raise ValueError("Null bytes are not allowed in input")
    if len(subject) > _MAX_SUBJECT_LEN:
        raise ValueError(f"Subject too long (max {_MAX_SUBJECT_LEN} chars)")
    if len(script) > _MAX_SCRIPT_LEN:
        raise ValueError(f"Script too long (max {_MAX_SCRIPT_LEN} chars)")
    if len(niche) > _MAX_NICHE_LEN:
        raise ValueError(f"Niche too long (max {_MAX_NICHE_LEN} chars)")
    if platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Unsupported platform '{platform}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_PLATFORMS))}"
        )


# ---------------------------------------------------------------------------
# Prompt builders (platform-specific)
# ---------------------------------------------------------------------------

def _build_title_prompt(subject: str, niche: str, platform: str, language: str) -> str:
    """Build the LLM prompt for title generation."""
    limits = _PLATFORM_LIMITS[platform]
    max_chars = limits["title"]

    return f"""You are an expert {platform} SEO specialist. Generate ONE highly optimized video title.

SUBJECT: {subject}
NICHE: {niche}
PLATFORM: {platform}
LANGUAGE: {language}
MAX CHARACTERS: {max_chars}

RULES:
1. Place the primary keyword within the first 5 words
2. Use power words that trigger curiosity (e.g., "Secret", "Shocking", "How I", "Nobody Talks About")
3. Include a number if relevant (e.g., "5 Ways", "$10K", "30 Days")
4. Do NOT include hashtags in the title
5. Do NOT use clickbait that misrepresents the content
6. Keep it under {max_chars} characters
7. Make it compelling enough to stop scrolling
8. Write in {language}

Return ONLY the title text, nothing else."""


def _build_description_prompt(
    subject: str, script: str, niche: str, platform: str, language: str
) -> str:
    """Build the LLM prompt for description generation."""
    limits = _PLATFORM_LIMITS[platform]
    max_chars = limits["description"]

    platform_specific = ""
    if platform == "youtube":
        platform_specific = """
- Start with a strong hook sentence (this appears in search results)
- Include 2-3 relevant keywords naturally in the first 2 sentences
- Add a brief content summary (3-4 sentences)
- Include a call-to-action (subscribe, like, comment)
- End with related search terms naturally woven in"""
    elif platform == "tiktok":
        platform_specific = """
- Keep it concise and punchy (under 300 chars for best engagement)
- Front-load the hook — first line must grab attention
- Use line breaks for readability
- Include a question to drive comments"""
    elif platform == "twitter":
        platform_specific = """
- Must be under 280 characters including hashtags
- Lead with the hook
- Use conversational, shareable language
- Include a call-to-action (retweet, reply)"""

    script_excerpt = script[:1500] if script else "No script provided."

    return f"""You are an expert {platform} SEO specialist. Generate an optimized video description.

SUBJECT: {subject}
NICHE: {niche}
PLATFORM: {platform}
LANGUAGE: {language}
MAX CHARACTERS: {max_chars}

SCRIPT EXCERPT (for context):
{script_excerpt}

PLATFORM-SPECIFIC RULES:
{platform_specific}

GENERAL RULES:
1. Write naturally — no keyword stuffing
2. Include relevant keywords that people search for
3. Write in {language}
4. Do NOT include hashtags in the description (they go separately)
5. Keep under {max_chars} characters

Return ONLY the description text, nothing else."""


def _build_tags_prompt(subject: str, niche: str, language: str) -> str:
    """Build the LLM prompt for tag generation (YouTube only)."""
    return f"""You are an expert YouTube SEO specialist. Generate 15-20 relevant tags for a video.

SUBJECT: {subject}
NICHE: {niche}
LANGUAGE: {language}

RULES:
1. Include a mix of: broad tags, specific tags, long-tail keyword tags
2. Put the most relevant tags first
3. Include common misspellings of key terms if applicable
4. Each tag should be 2-5 words
5. Total character count of all tags combined must be under 500
6. Do NOT include # symbols
7. Write in {language}

Return ONLY a JSON array of strings, e.g., ["tag one", "tag two", "tag three"]
Do NOT include any other text."""


def _build_hashtags_prompt(
    subject: str, niche: str, platform: str, count: int, language: str
) -> str:
    """Build the LLM prompt for hashtag generation."""
    return f"""You are an expert {platform} SEO specialist. Generate exactly {count} hashtags.

SUBJECT: {subject}
NICHE: {niche}
PLATFORM: {platform}
LANGUAGE: {language}

RULES:
1. First 2-3 hashtags should be high-volume, broad hashtags (e.g., #Shorts, #Viral)
2. Next 3-4 should be niche-specific hashtags
3. Last 2-3 should be long-tail/unique hashtags
4. Each hashtag MUST start with #
5. No spaces within hashtags (use CamelCase for multi-word)
6. Keep each hashtag under 30 characters
7. Return exactly {count} hashtags
8. Write in {language}

Return ONLY a JSON array of strings, e.g., ["#Shorts", "#NicheTopic", "#UniqueTag"]
Do NOT include any other text."""


def _build_hooks_prompt(subject: str, niche: str, platform: str, language: str) -> str:
    """Build the LLM prompt for engagement hook generation."""
    return f"""You are a viral content strategist for {platform}. Generate 3 scroll-stopping opening hooks.

SUBJECT: {subject}
NICHE: {niche}
PLATFORM: {platform}
LANGUAGE: {language}

RULES:
1. Each hook must be 1-2 sentences maximum
2. Must create immediate curiosity or tension
3. Use patterns proven to retain viewers:
   - "Did you know..." / "Most people don't know..."
   - "Stop scrolling if you..." / "This changed everything..."
   - Controversial opinion / Surprising stat / Direct question
4. Each hook should take a different approach
5. Write in {language}

Return ONLY a JSON array of 3 strings, e.g., ["hook 1", "hook 2", "hook 3"]
Do NOT include any other text."""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

_MAX_LLM_RESPONSE_LEN = 10000  # Cap LLM response length before parsing


def _parse_json_array(text: str) -> list[str]:
    """Safely parse a JSON array from LLM output."""
    # Cap length to prevent ReDoS on malformed LLM output
    cleaned = text[:_MAX_LLM_RESPONSE_LEN].strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # Try direct JSON parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return [str(item).strip() for item in result if item]
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: extract array with regex
    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(item).strip() for item in result if item]
        except (json.JSONDecodeError, TypeError):
            pass

    return []


def _clean_title(title: str, max_chars: int) -> str:
    """Clean and truncate a title to fit platform limits."""
    # Remove quotes, leading/trailing whitespace
    title = title.strip().strip('"').strip("'").strip()
    # Remove any hashtags that snuck in
    title = re.sub(r"#\S+", "", title).strip()
    # Truncate if needed
    if len(title) > max_chars:
        title = title[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    return title


def _clean_description(description: str, max_chars: int) -> str:
    """Clean and truncate a description to fit platform limits."""
    description = description.strip().strip('"').strip("'").strip()
    if len(description) > max_chars:
        description = description[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    return description


def _clean_hashtags(hashtags: list[str], max_count: int) -> list[str]:
    """Normalize hashtags: ensure # prefix, remove duplicates, enforce limit."""
    seen = set()
    cleaned = []
    for tag in hashtags:
        tag = tag.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        # Remove spaces within hashtag
        tag = tag.replace(" ", "")
        # Limit individual hashtag length
        if len(tag) > 30:
            tag = tag[:30]
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            cleaned.append(tag)
        if len(cleaned) >= max_count:
            break
    return cleaned


def _clean_tags(tags: list[str], max_total_chars: int) -> list[str]:
    """Clean tags: remove duplicates, enforce total character limit."""
    seen = set()
    cleaned = []
    total_chars = 0
    for tag in tags:
        tag = tag.strip().strip("#")
        if not tag:
            continue
        tag_lower = tag.lower()
        if tag_lower in seen:
            continue
        if total_chars + len(tag) + (1 if cleaned else 0) > max_total_chars:
            break
        seen.add(tag_lower)
        cleaned.append(tag)
        total_chars += len(tag) + (1 if len(cleaned) > 1 else 0)
    return cleaned


# ---------------------------------------------------------------------------
# Score estimator
# ---------------------------------------------------------------------------

def _estimate_seo_score(result: SEOResult) -> int:
    """Estimate a 0-100 SEO quality score based on completeness heuristics."""
    score = 0
    limits = _PLATFORM_LIMITS.get(result.platform, _PLATFORM_LIMITS["youtube"])

    # Title quality (0-30)
    if result.title:
        score += 10
        if 30 <= len(result.title) <= limits.get("title", 100):
            score += 10  # Good length
        if any(c.isdigit() for c in result.title):
            score += 5  # Contains a number
        if any(w in result.title.lower() for w in ["how", "why", "what", "secret", "best", "top"]):
            score += 5  # Power word

    # Description quality (0-25)
    if result.description:
        score += 10
        if len(result.description) > 100:
            score += 10  # Substantial description
        if "?" in result.description:
            score += 5  # Contains a question (engagement driver)

    # Tags quality (0-15)
    if result.tags:
        score += 5
        if len(result.tags) >= 10:
            score += 5
        if len(result.tags) >= 15:
            score += 5

    # Hashtags quality (0-15)
    if result.hashtags:
        score += 5
        if len(result.hashtags) >= 5:
            score += 5
        if any(h.lower() in ("#shorts", "#viral", "#fyp", "#foryou") for h in result.hashtags):
            score += 5  # Platform-specific discovery hashtags

    # Hooks quality (0-15)
    if result.hooks:
        score += 5
        if len(result.hooks) >= 3:
            score += 10

    return min(score, 100)


# ---------------------------------------------------------------------------
# Main optimization function
# ---------------------------------------------------------------------------

def optimize_metadata(
    subject: str,
    script: str = "",
    niche: str = "",
    platform: str = "youtube",
    language: str = "",
    generate_fn=None,
) -> SEOResult:
    """
    Generate SEO-optimized metadata for a video.

    Args:
        subject: The video topic/subject.
        script: The video script text (optional, improves description quality).
        niche: The content niche (e.g., "tech", "finance", "cooking").
        platform: Target platform ("youtube", "tiktok", "twitter").
        language: Target language (default from config or "en").
        generate_fn: LLM text generation function (default: llm_provider.generate_text).
                     Signature: generate_fn(prompt: str) -> str

    Returns:
        SEOResult with optimized title, description, tags, hashtags, hooks.

    Raises:
        ValueError: On invalid input.
    """
    # Resolve defaults from config
    if not language:
        language = get_seo_language() or "en"
    if not niche:
        niche = "general"

    # Truncate inputs for safety
    subject = subject[:_MAX_SUBJECT_LEN]
    script = script[:_MAX_SCRIPT_LEN]
    niche = niche[:_MAX_NICHE_LEN]

    # Validate
    _validate_input(subject, script, niche, platform)

    # Resolve LLM generation function
    if generate_fn is None:
        from llm_provider import generate_text
        generate_fn = generate_text

    limits = _PLATFORM_LIMITS[platform]
    result = SEOResult(platform=platform)

    # --- Generate title ---
    title_prompt = _build_title_prompt(subject, niche, platform, language)
    raw_title = generate_fn(title_prompt)
    result.title = _clean_title(raw_title, limits.get("title", 100))

    # Rate limit between LLM calls to avoid API throttling
    time.sleep(_LLM_CALL_DELAY)

    # --- Generate description ---
    desc_prompt = _build_description_prompt(subject, script, niche, platform, language)
    raw_desc = generate_fn(desc_prompt)
    result.description = _clean_description(raw_desc, limits.get("description", 5000))

    # --- Generate tags (YouTube only) ---
    if platform == "youtube" and get_seo_include_tags():
        time.sleep(_LLM_CALL_DELAY)
        tags_prompt = _build_tags_prompt(subject, niche, language)
        raw_tags = generate_fn(tags_prompt)
        parsed_tags = _parse_json_array(raw_tags)
        result.tags = _clean_tags(parsed_tags, limits.get("tags", 500))

    # --- Generate hashtags ---
    time.sleep(_LLM_CALL_DELAY)
    hashtag_count = get_seo_hashtag_count()
    max_hashtags = limits.get("hashtags", 10)
    target_count = min(hashtag_count, max_hashtags)
    hashtags_prompt = _build_hashtags_prompt(subject, niche, platform, target_count, language)
    raw_hashtags = generate_fn(hashtags_prompt)
    parsed_hashtags = _parse_json_array(raw_hashtags)
    result.hashtags = _clean_hashtags(parsed_hashtags, max_hashtags)

    # --- Generate hooks ---
    if get_seo_include_hooks():
        time.sleep(_LLM_CALL_DELAY)
        hooks_prompt = _build_hooks_prompt(subject, niche, platform, language)
        raw_hooks = generate_fn(hooks_prompt)
        parsed_hooks = _parse_json_array(raw_hooks)
        result.hooks = [h for h in parsed_hooks[:3] if h]

    # --- Score the result ---
    result.score = _estimate_seo_score(result)

    return result


def optimize_existing_metadata(
    metadata: dict,
    niche: str = "",
    platform: str = "youtube",
    language: str = "",
    generate_fn=None,
) -> SEOResult:
    """
    Take existing metadata (title, description) and enhance it with SEO optimization.

    Args:
        metadata: Dict with at least "title" key. May include "description", "subject".
        niche: Content niche.
        platform: Target platform.
        language: Target language.
        generate_fn: LLM generation function.

    Returns:
        SEOResult with enhanced metadata.
    """
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a dict")

    subject = str(metadata.get("subject", metadata.get("title", "")))
    script = str(metadata.get("script", metadata.get("description", "")))

    return optimize_metadata(
        subject=subject,
        script=script,
        niche=niche,
        platform=platform,
        language=language,
        generate_fn=generate_fn,
    )
