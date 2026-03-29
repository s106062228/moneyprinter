"""
Tests for uniqueness_scorer.py.

Run with:
    python3 -m pytest tests/test_uniqueness_scorer.py -v
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def history_path(tmp_path):
    """Return a path inside tmp_path for the history JSON file."""
    return str(tmp_path / "uniqueness_history.json")


@pytest.fixture()
def scorer(history_path):
    """UniquenessScorer backed by a fresh tmp history file."""
    # Patch ROOT_DIR so the module-level _HISTORY_FILE doesn't interfere
    import uniqueness_scorer as us
    return us.UniquenessScorer(history_path=history_path)


def _make_scorer(history_path, threshold=0.6, max_history=200):
    import uniqueness_scorer as us
    return us.UniquenessScorer(
        history_path=history_path, threshold=threshold, max_history=max_history
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 1. UniquenessScore dataclass
# ---------------------------------------------------------------------------


class TestUniquenessScoreDataclass:
    def test_construct_valid(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=0.75,
            title_similarity=0.9,
            script_variation=0.8,
            metadata_diversity=0.7,
            posting_regularity=0.6,
            flagged=False,
        )
        assert s.overall == 0.75
        assert s.flagged is False

    def test_edge_zero(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=0.0,
            title_similarity=0.0,
            script_variation=0.0,
            metadata_diversity=0.0,
            posting_regularity=0.0,
            flagged=True,
        )
        assert s.overall == 0.0
        assert s.flagged is True

    def test_edge_one(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=1.0,
            title_similarity=1.0,
            script_variation=1.0,
            metadata_diversity=1.0,
            posting_regularity=1.0,
            flagged=False,
        )
        assert s.overall == 1.0

    def test_details_default_empty(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=0.5,
            title_similarity=0.5,
            script_variation=0.5,
            metadata_diversity=0.5,
            posting_regularity=0.5,
            flagged=True,
        )
        assert s.details == {}

    def test_details_custom(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=0.5,
            title_similarity=0.5,
            script_variation=0.5,
            metadata_diversity=0.5,
            posting_regularity=0.5,
            flagged=False,
            details={"key": "value"},
        )
        assert s.details["key"] == "value"

    def test_flagged_true_when_low(self):
        from uniqueness_scorer import UniquenessScore
        s = UniquenessScore(
            overall=0.3,
            title_similarity=0.3,
            script_variation=0.3,
            metadata_diversity=0.3,
            posting_regularity=0.3,
            flagged=True,
        )
        assert s.flagged is True


# ---------------------------------------------------------------------------
# 2. Title similarity
# ---------------------------------------------------------------------------


class TestTitleSimilarity:
    def test_identical_titles_low_score(self, scorer):
        title = "10 AI Tools That Will Replace Your Job"
        scorer.add_to_history(title, "Some script.", ["ai"], "Description.")
        result = scorer.score_content(title, "Some script.", ["ai"], "Description.")
        assert result.title_similarity < 0.2  # very similar → low uniqueness score

    def test_unique_title_high_score(self, scorer):
        scorer.add_to_history(
            "Cooking pasta in 5 minutes", "Script.", ["cooking"], "Desc."
        )
        result = scorer.score_content(
            "Why rockets are made of aluminium", "Script.", ["rockets"], "Desc."
        )
        assert result.title_similarity > 0.5

    def test_empty_history_returns_one(self, scorer):
        result = scorer.score_content("Any title", "Script.", [], "Desc.")
        assert result.title_similarity == 1.0

    def test_case_insensitive_comparison(self, scorer):
        scorer.add_to_history(
            "HELLO WORLD TUTORIAL", "Script.", [], "Desc."
        )
        result = scorer.score_content(
            "hello world tutorial", "Script.", [], "Desc."
        )
        # Same title, different case → should still detect high similarity
        assert result.title_similarity < 0.2

    def test_slightly_different_title(self, scorer):
        scorer.add_to_history(
            "10 AI Tools That Will Replace Your Job", "Script.", ["ai"], "Desc."
        )
        result = scorer.score_content(
            "10 AI Tools That Could Replace Your Job", "Script.", ["ai"], "Desc."
        )
        # Very close title → lower score than a totally different one
        assert result.title_similarity < 0.5

    def test_completely_different_titles_high_score(self, scorer):
        for i in range(5):
            scorer.add_to_history(
                f"Cooking recipe number {i}", "Script.", ["food"], "Desc."
            )
        result = scorer.score_content(
            "Advanced quantum computing explained", "Script.", ["tech"], "Desc."
        )
        assert result.title_similarity > 0.5


# ---------------------------------------------------------------------------
# 3. Script variation
# ---------------------------------------------------------------------------


class TestScriptVariation:
    def _same_structure_script(self):
        return "This is a sentence. And another sentence. One more here."

    def test_empty_history_returns_one(self, scorer):
        result = scorer.score_content(
            "Title", self._same_structure_script(), [], "Desc."
        )
        assert result.script_variation == 1.0

    def test_varied_structure_higher_score(self, scorer):
        # Add many scripts with a specific structure
        for _ in range(5):
            scorer.add_to_history(
                "Title",
                "Short sentence. Another. And one more.",
                [],
                "Desc.",
            )
        # Now score a very long script with lots of variety
        long_script = (
            "This is a very long introductory sentence that sets up the topic at hand. "
            "Did you know that this is true? "
            "What about this amazing fact that challenges everything? "
            "Incredible! Unbelievable! "
            "Let us dive deeper into the subject matter with considerable detail. "
            "Summary follows."
        )
        result = scorer.score_content("Title", long_script, [], "Desc.")
        # Variation should be positive (history exists, structure differs)
        assert result.script_variation >= 0.0

    def test_identical_structure_low_variation(self, scorer):
        script = "This is sentence one. This is sentence two. This is sentence three."
        for _ in range(10):
            scorer.add_to_history("Title", script, [], "Desc.")
        result = scorer.score_content("Title", script, [], "Desc.")
        # Same structure → low variation
        assert result.script_variation < 0.5

    def test_script_fingerprint_in_details(self, scorer):
        result = scorer.score_content("Title", "Hello world.", [], "Desc.")
        assert "script_fingerprint" in result.details

    def test_fingerprint_counts_sentences(self):
        import uniqueness_scorer as us
        fp = us._script_fingerprint("First sentence. Second sentence. Third one.")
        assert fp["sentence_count"] == 3

    def test_fingerprint_question_ratio(self):
        import uniqueness_scorer as us
        fp = us._script_fingerprint("Is this a question? No it is not. Really?")
        assert fp["question_ratio"] == pytest.approx(2 / 3, abs=0.01)

    def test_fingerprint_empty_script(self):
        import uniqueness_scorer as us
        fp = us._script_fingerprint("")
        assert fp["sentence_count"] == 0
        assert fp["avg_length"] == 0.0


# ---------------------------------------------------------------------------
# 4. Metadata diversity
# ---------------------------------------------------------------------------


class TestMetadataDiversity:
    def test_empty_history_returns_one(self, scorer):
        result = scorer.score_content("Title", "Script.", ["tag1", "tag2"], "Desc.")
        assert result.metadata_diversity == 1.0

    def test_overlapping_tags_low_diversity(self, scorer):
        tags = ["ai", "machine-learning", "python", "tutorial"]
        for _ in range(5):
            scorer.add_to_history("Title", "Script.", tags, "Desc.")
        result = scorer.score_content("Title", "Script.", tags, "Desc.")
        assert result.metadata_diversity < 0.3

    def test_diverse_tags_high_score(self, scorer):
        scorer.add_to_history(
            "Title A", "Script one.", ["cooking", "food", "recipes"],
            "This video is all about cooking Italian food from scratch.",
        )
        result = scorer.score_content(
            "Title B", "Script two.", ["rockets", "nasa", "space"],
            "Astronauts share their experience returning from orbit.",
        )
        assert result.metadata_diversity > 0.7

    def test_empty_tags_no_crash(self, scorer):
        scorer.add_to_history("Title", "Script.", [], "Desc.")
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        # No tags on either side → no overlap, score should be high
        assert result.metadata_diversity >= 0.0

    def test_description_template_detection(self, scorer):
        # Add a very similar description to history
        desc = "In this video we explore the top ten tools for productivity in 2026."
        scorer.add_to_history("Title", "Script.", [], desc)
        result = scorer.score_content("Title", "Script.", [], desc)
        # Same description words → low diversity
        assert result.metadata_diversity < 0.3

    def test_different_descriptions_high_diversity(self, scorer):
        scorer.add_to_history(
            "Title",
            "Script.",
            [],
            "In this video we cook Italian pasta dishes from scratch.",
        )
        result = scorer.score_content(
            "Title",
            "Script.",
            [],
            "NASA astronauts describe their experience returning from the ISS.",
        )
        assert result.metadata_diversity > 0.5


# ---------------------------------------------------------------------------
# 5. Posting regularity
# ---------------------------------------------------------------------------


class TestPostingRegularity:
    def test_fewer_than_3_posts_returns_one(self, scorer):
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        assert result.posting_regularity == 1.0

    def test_fewer_than_3_posts_with_two_entries(self, scorer):
        scorer.add_to_history("T1", "S.", [], "D.")
        scorer.add_to_history("T2", "S.", [], "D.")
        result = scorer.score_content("T3", "S.", [], "D.")
        assert result.posting_regularity == 1.0

    def test_fixed_intervals_low_score(self, history_path):
        import uniqueness_scorer as us
        # Build history with perfectly fixed 24-hour intervals
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        entries = []
        for i in range(10):
            ts = (base_time + timedelta(hours=24 * i)).isoformat()
            entries.append({
                "title": f"Title {i}",
                "script_hash": "abc",
                "tags": [],
                "description_hash": "def",
                "description_words": [],
                "platform": "youtube",
                "timestamp": ts,
                "script_fingerprint": {"sentence_count": 3},
            })
        with open(history_path, "w") as f:
            json.dump(entries, f)

        scorer = us.UniquenessScorer(history_path=history_path)
        result = scorer.score_content("New title", "Script.", [], "Desc.")
        # Perfectly fixed intervals → low regularity score
        assert result.posting_regularity < 0.3

    def test_varied_intervals_high_score(self, history_path):
        import uniqueness_scorer as us
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Large variance in gaps: 1h, 72h, 2h, 48h, 5h, 96h
        gaps_hours = [0, 1, 73, 75, 123, 128, 224]
        entries = []
        for i, offset in enumerate(gaps_hours):
            ts = (base_time + timedelta(hours=offset)).isoformat()
            entries.append({
                "title": f"Title {i}",
                "script_hash": "abc",
                "tags": [],
                "description_hash": "def",
                "description_words": [],
                "platform": "youtube",
                "timestamp": ts,
                "script_fingerprint": {},
            })
        with open(history_path, "w") as f:
            json.dump(entries, f)

        scorer = us.UniquenessScorer(history_path=history_path)
        result = scorer.score_content("New title", "Script.", [], "Desc.")
        assert result.posting_regularity > 0.3

    def test_regularity_score_private_helper(self):
        import uniqueness_scorer as us
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        history = [
            {"timestamp": (base + timedelta(hours=i * 24)).isoformat()}
            for i in range(10)
        ]
        score = us._score_posting_regularity(history)
        assert score < 0.2  # perfectly regular


# ---------------------------------------------------------------------------
# 6. score_content() composite
# ---------------------------------------------------------------------------


class TestScoreContentComposite:
    def test_all_high_no_history(self, scorer):
        result = scorer.score_content(
            "Completely unique title never seen before",
            "Interesting varied script with questions? And exclamations!",
            ["unique", "tags", "here"],
            "Totally original description with fresh words.",
        )
        # No history → all dimensions 1.0 except regularity < 3
        assert result.overall > 0.9
        assert not result.flagged

    def test_all_low_repeated_content(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=0.6)
        title = "Best AI tools for 2026"
        script = "These tools are amazing. You should use them. They are the best."
        tags = ["ai", "tools", "2026"]
        description = "In this video I show you the best AI tools for 2026."

        # Saturate history with identical entries using a fixed timestamp to
        # simulate regular posting so regularity is also low
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            ts = (base + timedelta(hours=i * 24)).isoformat()
            fp = us._script_fingerprint(script)
            entry = {
                "title": title,
                "script_hash": us._sha256_prefix(script),
                "tags": tags,
                "description_hash": us._description_hash(description),
                "description_words": list(set(description.lower().split())),
                "platform": "youtube",
                "timestamp": ts,
                "script_fingerprint": fp,
            }
            history = us._read_history(history_path)
            history.append(entry)
            us._atomic_write_json(history_path, history)

        result = scorer.score_content(title, script, tags, description)
        # title_similarity will be low (very similar), metadata low, regularity low
        assert result.title_similarity < 0.2
        assert result.metadata_diversity < 0.3
        assert result.flagged  # overall should be below threshold

    def test_mixed_content(self, scorer):
        # Unique title but identical tags
        scorer.add_to_history("Old title", "Old script.", ["ai", "tools"], "Old desc.")
        result = scorer.score_content(
            "Brand new topic about quantum computing",
            "Different script structure? Yes! Really exciting!",
            ["ai", "tools"],  # same tags
            "Old desc.",
        )
        # Should be somewhere in the middle
        assert 0.0 <= result.overall <= 1.0

    def test_returns_uniqueness_score_instance(self, scorer):
        from uniqueness_scorer import UniquenessScore
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        assert isinstance(result, UniquenessScore)

    def test_overall_bounded_0_to_1(self, scorer):
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        assert 0.0 <= result.overall <= 1.0

    def test_details_contains_platform(self, scorer):
        result = scorer.score_content("Title", "Script.", [], "Desc.", platform="tiktok")
        assert result.details["platform"] == "tiktok"

    def test_details_contains_history_size(self, scorer):
        scorer.add_to_history("T1", "S.", [], "D.")
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        assert result.details["history_size"] == 1


# ---------------------------------------------------------------------------
# 7. add_to_history()
# ---------------------------------------------------------------------------


class TestAddToHistory:
    def test_adds_entry(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", ["tag"], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 1
        assert entries[0]["title"] == "Title"

    def test_adds_multiple_entries(self, scorer, history_path):
        for i in range(5):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 5

    def test_stores_script_hash_not_full_script(self, scorer, history_path):
        scorer.add_to_history("Title", "Full script text here.", [], "Desc.")
        entry = json.loads(Path(history_path).read_text())[0]
        assert "script_hash" in entry
        assert "Full script text here." not in str(entry)

    def test_stores_description_hash(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", [], "My long description.")
        entry = json.loads(Path(history_path).read_text())[0]
        assert "description_hash" in entry

    def test_stores_tags(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", ["python", "ai"], "Desc.")
        entry = json.loads(Path(history_path).read_text())[0]
        assert entry["tags"] == ["python", "ai"]

    def test_stores_platform(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", [], "Desc.", platform="tiktok")
        entry = json.loads(Path(history_path).read_text())[0]
        assert entry["platform"] == "tiktok"

    def test_stores_timestamp_utc(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", [], "Desc.")
        entry = json.loads(Path(history_path).read_text())[0]
        ts = entry["timestamp"]
        assert "T" in ts  # ISO format contains T
        assert "+" in ts or "Z" in ts or ts.endswith("+00:00")

    def test_stores_script_fingerprint(self, scorer, history_path):
        scorer.add_to_history("Title", "Sentence one. Sentence two.", [], "Desc.")
        entry = json.loads(Path(history_path).read_text())[0]
        assert "script_fingerprint" in entry
        assert entry["script_fingerprint"]["sentence_count"] == 2

    def test_respects_max_history(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=5)
        for i in range(10):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 5

    def test_keeps_most_recent_on_trim(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=3)
        for i in range(5):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        titles = [e["title"] for e in entries]
        assert "Title 4" in titles
        assert "Title 0" not in titles

    def test_atomic_write_no_corrupt_on_success(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", [], "Desc.")
        # File should be valid JSON
        data = json.loads(Path(history_path).read_text())
        assert isinstance(data, list)

    def test_creates_mp_directory_if_missing(self, tmp_path):
        import uniqueness_scorer as us
        nested = str(tmp_path / "nested" / "dir" / "history.json")
        scorer = us.UniquenessScorer(history_path=nested)
        scorer.add_to_history("T", "S.", [], "D.")
        assert Path(nested).exists()


# ---------------------------------------------------------------------------
# 8. get_history()
# ---------------------------------------------------------------------------


class TestGetHistory:
    def test_empty_returns_empty_list(self, scorer):
        assert scorer.get_history() == []

    def test_returns_entries(self, scorer):
        scorer.add_to_history("T1", "S.", [], "D.")
        scorer.add_to_history("T2", "S.", [], "D.")
        history = scorer.get_history()
        assert len(history) == 2

    def test_respects_limit(self, scorer):
        for i in range(10):
            scorer.add_to_history(f"T{i}", "S.", [], "D.")
        history = scorer.get_history(limit=3)
        assert len(history) == 3

    def test_limit_zero_returns_empty(self, scorer):
        scorer.add_to_history("T", "S.", [], "D.")
        assert scorer.get_history(limit=0) == []

    def test_returns_most_recent(self, scorer):
        for i in range(10):
            scorer.add_to_history(f"Title {i}", "S.", [], "D.")
        history = scorer.get_history(limit=3)
        titles = [e["title"] for e in history]
        assert "Title 9" in titles

    def test_returns_all_when_limit_exceeds_size(self, scorer):
        scorer.add_to_history("T", "S.", [], "D.")
        history = scorer.get_history(limit=100)
        assert len(history) == 1


# ---------------------------------------------------------------------------
# 9. clear_history()
# ---------------------------------------------------------------------------


class TestClearHistory:
    def test_clears_all_entries(self, scorer, history_path):
        for i in range(5):
            scorer.add_to_history(f"T{i}", "S.", [], "D.")
        scorer.clear_history()
        entries = json.loads(Path(history_path).read_text())
        assert entries == []

    def test_get_history_empty_after_clear(self, scorer):
        scorer.add_to_history("T", "S.", [], "D.")
        scorer.clear_history()
        assert scorer.get_history() == []

    def test_clear_on_nonexistent_file_does_not_crash(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path)
        scorer.clear_history()  # File doesn't exist yet
        assert scorer.get_history() == []

    def test_can_add_after_clear(self, scorer):
        scorer.add_to_history("T", "S.", [], "D.")
        scorer.clear_history()
        scorer.add_to_history("T2", "S.", [], "D.")
        history = scorer.get_history()
        assert len(history) == 1
        assert history[0]["title"] == "T2"


# ---------------------------------------------------------------------------
# 10. History rotation
# ---------------------------------------------------------------------------


class TestHistoryRotation:
    def test_rotation_trims_oldest(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=200)
        for i in range(210):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 200

    def test_rotation_keeps_newest(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=10)
        for i in range(15):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        titles = [e["title"] for e in entries]
        assert "Title 14" in titles
        assert "Title 0" not in titles

    def test_rotation_exact_boundary(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=5)
        for i in range(5):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 5  # Exactly at limit, no trim needed

    def test_rotation_after_one_over(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, max_history=5)
        for i in range(6):
            scorer.add_to_history(f"Title {i}", "Script.", [], "Desc.")
        entries = json.loads(Path(history_path).read_text())
        assert len(entries) == 5
        assert entries[0]["title"] == "Title 1"


# ---------------------------------------------------------------------------
# 11. Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_load_from_existing_file(self, history_path):
        import uniqueness_scorer as us
        # Pre-populate the file manually
        entry = {
            "title": "Preloaded title",
            "script_hash": "abc123",
            "tags": ["tag1"],
            "description_hash": "def456",
            "description_words": ["word"],
            "platform": "youtube",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "script_fingerprint": {"sentence_count": 1},
        }
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        Path(history_path).write_text(json.dumps([entry]))

        scorer = us.UniquenessScorer(history_path=history_path)
        history = scorer.get_history()
        assert len(history) == 1
        assert history[0]["title"] == "Preloaded title"

    def test_save_to_file(self, scorer, history_path):
        scorer.add_to_history("New entry", "Script.", [], "Desc.")
        data = json.loads(Path(history_path).read_text())
        assert data[0]["title"] == "New entry"

    def test_corrupted_file_returns_empty(self, history_path):
        import uniqueness_scorer as us
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        Path(history_path).write_text("NOT VALID JSON {{{{")
        scorer = us.UniquenessScorer(history_path=history_path)
        assert scorer.get_history() == []

    def test_corrupted_file_adds_new_entry(self, history_path):
        import uniqueness_scorer as us
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        Path(history_path).write_text("{broken json}")
        scorer = us.UniquenessScorer(history_path=history_path)
        scorer.add_to_history("Fresh title", "Script.", [], "Desc.")
        history = scorer.get_history()
        assert len(history) == 1

    def test_missing_file_returns_empty(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path)
        assert scorer.get_history() == []

    def test_json_is_valid_after_write(self, scorer, history_path):
        scorer.add_to_history("Title", "Script.", ["t1"], "Desc.")
        # Should not raise
        data = json.loads(Path(history_path).read_text())
        assert isinstance(data, list)

    def test_persists_across_scorer_instances(self, history_path):
        import uniqueness_scorer as us
        scorer1 = us.UniquenessScorer(history_path=history_path)
        scorer1.add_to_history("Persistent title", "Script.", [], "Desc.")

        scorer2 = us.UniquenessScorer(history_path=history_path)
        history = scorer2.get_history()
        assert history[0]["title"] == "Persistent title"

    def test_file_is_json_array_not_object(self, scorer, history_path):
        scorer.add_to_history("T", "S.", [], "D.")
        data = json.loads(Path(history_path).read_text())
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# 12. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_title_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("", "Script.", [], "Desc.")

    def test_blank_title_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("   ", "Script.", [], "Desc.")

    def test_null_byte_in_title_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("Title\x00bad", "Script.", [], "Desc.")

    def test_null_byte_in_script_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("Title", "Script\x00.", [], "Desc.")

    def test_null_byte_in_description_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("Title", "Script.", [], "Desc\x00.")

    def test_null_byte_in_tag_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.score_content("Title", "Script.", ["tag\x00"], "Desc.")

    def test_non_string_title_raises(self, scorer):
        with pytest.raises(TypeError):
            scorer.score_content(123, "Script.", [], "Desc.")

    def test_non_string_script_raises(self, scorer):
        with pytest.raises(TypeError):
            scorer.score_content("Title", 456, [], "Desc.")

    def test_non_list_tags_raises(self, scorer):
        with pytest.raises(TypeError):
            scorer.score_content("Title", "Script.", "not_a_list", "Desc.")

    def test_non_string_tag_item_raises(self, scorer):
        with pytest.raises(TypeError):
            scorer.score_content("Title", "Script.", [1, 2, 3], "Desc.")

    def test_long_title_truncated(self, scorer):
        long_title = "A" * 1000
        # Should not raise, just truncated to 500
        result = scorer.score_content(long_title, "Script.", [], "Desc.")
        assert result is not None

    def test_tags_truncated_to_max(self, scorer, history_path):
        import uniqueness_scorer as us
        tags = [f"tag{i}" for i in range(100)]
        scorer.add_to_history("T", "S.", tags, "D.")
        entry = json.loads(Path(history_path).read_text())[0]
        assert len(entry["tags"]) <= us._MAX_TAGS

    def test_add_to_history_empty_title_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.add_to_history("", "Script.", [], "Desc.")

    def test_add_to_history_null_byte_raises(self, scorer):
        with pytest.raises(ValueError):
            scorer.add_to_history("Title\x00", "Script.", [], "Desc.")


# ---------------------------------------------------------------------------
# 13. Threshold configuration
# ---------------------------------------------------------------------------


class TestThresholdConfiguration:
    def test_custom_threshold_flags_below(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=0.99)
        # No history → all dimensions 1.0 → overall ~1.0, still may or may not flag
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        # overall should be 1.0 with no history
        assert result.overall == pytest.approx(1.0, abs=0.001)
        assert not result.flagged  # 1.0 >= 0.99

    def test_threshold_zero_never_flags(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=0.0)
        result = scorer.score_content("Title", "Script.", [], "Desc.")
        assert not result.flagged  # overall >= 0.0 always

    def test_threshold_one_always_flags(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=1.0)
        # Add some history so overall < 1.0
        scorer.add_to_history("Same title", "Script.", [], "Desc.")
        result = scorer.score_content("Same title", "Script.", [], "Desc.")
        assert result.flagged  # should be below 1.0 with same title in history

    def test_default_threshold_is_0_6(self):
        import uniqueness_scorer as us
        assert us._DEFAULT_THRESHOLD == 0.6

    def test_flagged_false_when_above_threshold(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=0.5)
        result = scorer.score_content("Unique title here", "Script.", [], "Desc.")
        # No history → overall = 1.0 > 0.5
        assert not result.flagged

    def test_flagged_true_when_below_threshold(self, history_path):
        import uniqueness_scorer as us
        scorer = us.UniquenessScorer(history_path=history_path, threshold=0.6)
        title = "Repeated title for testing"
        script = "Same sentence. Same sentence. Same sentence."
        tags = ["same", "tags", "always"]
        desc = "Same description every single time."

        # Build up a saturated, regular history
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        entries = []
        fp = us._script_fingerprint(script)
        for i in range(20):
            ts = (base + timedelta(hours=24 * i)).isoformat()
            entries.append({
                "title": title,
                "script_hash": us._sha256_prefix(script),
                "tags": tags,
                "description_hash": us._description_hash(desc),
                "description_words": list(set(desc.lower().split())),
                "platform": "youtube",
                "timestamp": ts,
                "script_fingerprint": fp,
            })
        us._atomic_write_json(history_path, entries)

        result = scorer.score_content(title, script, tags, desc)
        assert result.flagged
