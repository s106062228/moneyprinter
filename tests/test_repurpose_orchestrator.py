"""
Tests for src/repurpose_orchestrator.py — Repurposing Orchestrator.

Coverage categories:
1.  RepurposeConfig dataclass (defaults, validate happy path)
2.  RepurposeConfig.validate() — all error cases
3.  ClipInfo dataclass (defaults, fields)
4.  RepurposeResult dataclass (defaults, fields)
5.  RepurposeOrchestrator.__init__ (defaults, config reading)
6.  run() — full happy path with auto_publish=True
7.  run() — clips only (auto_publish=False)
8.  run() — smart_clipper not available
9.  run() — export_optimizer not available
10. run() — publisher not available when auto_publish=True
11. run() — clip extraction returns empty
12. run() — clip extraction partial failure
13. run() — optimization failure for one platform (continues)
14. run() — publish failure for one clip (continues)
15. _clip() — filters by duration, limits to max_clips
16. _optimize() — creates optimized files per platform
17. _publish() — creates correct PublishJobs, title template
18. Title template — {index} replacement, no placeholder
19. Duration tracking — result.duration_seconds is set
20. Error accumulation — errors from all stages collected
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call

# ---------------------------------------------------------------------------
# Ensure src/ is on sys.path before importing the module under test
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC_DIR)

# ---------------------------------------------------------------------------
# Pre-stub heavy optional dependencies so the module can be imported without
# them actually being installed.  We ONLY mock modules that are not already
# importable — src/ modules (publisher, ffmpeg_utils, etc.) should import
# from the real source.  We also track injections so we can clean up after
# the test session to avoid contaminating later test files.
# ---------------------------------------------------------------------------
_INJECTED_MOCKS: dict[str, MagicMock] = {}

for _mod in (
    "scenedetect",
    "faster_whisper",
    "moviepy",
):
    if _mod not in sys.modules:
        _mock = MagicMock()
        sys.modules[_mod] = _mock
        _INJECTED_MOCKS[_mod] = _mock

# ---------------------------------------------------------------------------
# Import the module under test (AFTER stubbing deps)
# ---------------------------------------------------------------------------
import repurpose_orchestrator as ro

# Clean up injected mocks from sys.modules immediately after import so that
# later test files (test_publisher.py, test_smart_clipper.py, etc.) can
# import the real modules from src/ without contamination.
for _mod_name in list(_INJECTED_MOCKS):
    sys.modules.pop(_mod_name, None)
_INJECTED_MOCKS.clear()

from repurpose_orchestrator import (
    RepurposeConfig,
    ClipInfo,
    RepurposeResult,
    RepurposeOrchestrator,
    _MAX_CLIPS,
    _MIN_CLIP_DURATION,
    _MAX_CLIP_DURATION,
    _MAX_PATH_LENGTH,
    _SUPPORTED_FORMATS,
    _ALLOWED_PLATFORMS,
    _MAX_TITLE_LENGTH,
    _MAX_DESCRIPTION_LENGTH,
    _MAX_TAGS,
)


# ===========================================================================
# Shared helpers / fixtures
# ===========================================================================

@pytest.fixture()
def video_file(tmp_path):
    """Create a real (empty) .mp4 file so os.path.isfile() passes."""
    p = tmp_path / "source.mp4"
    p.write_bytes(b"")
    return str(p)


@pytest.fixture()
def output_dir(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    return str(d)


def _make_clip_candidate(start=0.0, end=30.0):
    """Build a minimal SmartClipper-style ClipCandidate mock."""
    cc = MagicMock()
    cc.start_time = start
    cc.end_time = end
    cc.duration = end - start
    cc.score = 7.0
    cc.transcript = "test"
    cc.reason = "engaging"
    return cc


def _make_publish_result(platform="youtube", ok=True):
    pr = MagicMock()
    pr.success = ok
    pr.platform = platform
    pr.error_type = "" if ok else "upload_error"
    return pr


# ===========================================================================
# 1. RepurposeConfig dataclass
# ===========================================================================

class TestRepurposeConfigDefaults:
    def test_required_field_source_video(self):
        cfg = RepurposeConfig(source_video="video.mp4")
        assert cfg.source_video == "video.mp4"

    def test_default_platforms(self):
        cfg = RepurposeConfig(source_video="v.mp4")
        assert cfg.platforms == ["youtube", "tiktok", "instagram"]

    def test_default_max_clips(self):
        assert RepurposeConfig(source_video="v.mp4").max_clips == 10

    def test_default_min_clip_duration(self):
        assert RepurposeConfig(source_video="v.mp4").min_clip_duration == 15.0

    def test_default_max_clip_duration(self):
        assert RepurposeConfig(source_video="v.mp4").max_clip_duration == 60.0

    def test_default_auto_publish(self):
        assert RepurposeConfig(source_video="v.mp4").auto_publish is False

    def test_default_title_template(self):
        assert RepurposeConfig(source_video="v.mp4").title_template == "Clip {index}"

    def test_default_description(self):
        assert RepurposeConfig(source_video="v.mp4").description == ""

    def test_default_tags(self):
        assert RepurposeConfig(source_video="v.mp4").tags == []

    def test_default_output_dir(self):
        assert RepurposeConfig(source_video="v.mp4").output_dir == ""

    def test_platforms_not_shared(self):
        a = RepurposeConfig(source_video="v.mp4")
        b = RepurposeConfig(source_video="v.mp4")
        a.platforms.append("twitter")
        assert "twitter" not in b.platforms


# ===========================================================================
# 2. RepurposeConfig.validate() — happy path
# ===========================================================================

class TestRepurposeConfigValidateHappy:
    def test_validate_passes_with_real_file(self, video_file):
        cfg = RepurposeConfig(source_video=video_file)
        cfg.validate()  # should not raise

    def test_validate_passes_with_output_dir(self, video_file, output_dir):
        cfg = RepurposeConfig(source_video=video_file, output_dir=output_dir)
        cfg.validate()

    def test_validate_all_allowed_platforms(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            platforms=["youtube", "tiktok", "twitter", "instagram"],
        )
        cfg.validate()


# ===========================================================================
# 3. RepurposeConfig.validate() — error cases
# ===========================================================================

class TestRepurposeConfigValidateErrors:
    # --- source_video ---
    def test_empty_source_video(self, video_file):
        cfg = RepurposeConfig(source_video="")
        with pytest.raises(ValueError, match="source_video must be a non-empty string"):
            cfg.validate()

    def test_null_bytes_in_source_video(self):
        cfg = RepurposeConfig(source_video="vid\x00eo.mp4")
        with pytest.raises(ValueError, match="null bytes"):
            cfg.validate()

    def test_too_long_source_video_path(self):
        long_path = "a" * (_MAX_PATH_LENGTH + 1) + ".mp4"
        cfg = RepurposeConfig(source_video=long_path)
        with pytest.raises(ValueError, match="exceeds maximum length"):
            cfg.validate()

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "video.xyz"
        f.write_bytes(b"")
        cfg = RepurposeConfig(source_video=str(f))
        with pytest.raises(ValueError, match="Unsupported video format"):
            cfg.validate()

    def test_missing_source_video(self):
        cfg = RepurposeConfig(source_video="/no/such/path/video.mp4")
        with pytest.raises(FileNotFoundError):
            cfg.validate()

    # --- max_clips ---
    def test_max_clips_zero(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, max_clips=0)
        with pytest.raises(ValueError, match="max_clips"):
            cfg.validate()

    def test_max_clips_too_high(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, max_clips=_MAX_CLIPS + 1)
        with pytest.raises(ValueError, match="max_clips"):
            cfg.validate()

    def test_max_clips_boundary_valid(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, max_clips=_MAX_CLIPS)
        cfg.validate()

    def test_max_clips_boundary_one(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, max_clips=1)
        cfg.validate()

    # --- durations ---
    def test_min_clip_duration_zero(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, min_clip_duration=0.0)
        with pytest.raises(ValueError, match="min_clip_duration"):
            cfg.validate()

    def test_min_clip_duration_negative(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, min_clip_duration=-5.0)
        with pytest.raises(ValueError, match="min_clip_duration"):
            cfg.validate()

    def test_max_less_than_min(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            min_clip_duration=30.0,
            max_clip_duration=10.0,
        )
        with pytest.raises(ValueError, match="max_clip_duration"):
            cfg.validate()

    def test_max_equal_to_min(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            min_clip_duration=30.0,
            max_clip_duration=30.0,
        )
        with pytest.raises(ValueError, match="max_clip_duration"):
            cfg.validate()

    # --- platforms ---
    def test_empty_platforms(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, platforms=[])
        with pytest.raises(ValueError, match="platforms must be a non-empty list"):
            cfg.validate()

    def test_unknown_platform(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, platforms=["snapchat"])
        with pytest.raises(ValueError, match="Unknown platform"):
            cfg.validate()

    def test_non_string_platform(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, platforms=[42])
        with pytest.raises(ValueError, match="Unknown platform"):
            cfg.validate()

    # --- title_template ---
    def test_title_template_too_long(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            title_template="x" * (_MAX_TITLE_LENGTH + 1),
        )
        with pytest.raises(ValueError, match="title_template exceeds"):
            cfg.validate()

    def test_title_template_boundary_valid(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            title_template="x" * _MAX_TITLE_LENGTH,
        )
        cfg.validate()

    # --- description ---
    def test_description_too_long(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            description="y" * (_MAX_DESCRIPTION_LENGTH + 1),
        )
        with pytest.raises(ValueError, match="description exceeds"):
            cfg.validate()

    def test_description_boundary_valid(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            description="y" * _MAX_DESCRIPTION_LENGTH,
        )
        cfg.validate()

    # --- output_dir ---
    def test_nonexistent_output_dir(self, video_file):
        cfg = RepurposeConfig(
            source_video=video_file,
            output_dir="/no/such/directory",
        )
        with pytest.raises(ValueError, match="output_dir does not exist"):
            cfg.validate()

    def test_empty_output_dir_skips_check(self, video_file):
        cfg = RepurposeConfig(source_video=video_file, output_dir="")
        cfg.validate()  # no error for empty string


# ===========================================================================
# 4. ClipInfo dataclass
# ===========================================================================

class TestClipInfo:
    def test_required_fields(self):
        c = ClipInfo(index=1, source_path="/tmp/clip1.mp4", duration=25.0)
        assert c.index == 1
        assert c.source_path == "/tmp/clip1.mp4"
        assert c.duration == 25.0

    def test_default_optimized_paths(self):
        c = ClipInfo(index=1, source_path="x.mp4", duration=10.0)
        assert c.optimized_paths == {}

    def test_default_published(self):
        c = ClipInfo(index=1, source_path="x.mp4", duration=10.0)
        assert c.published is False

    def test_default_errors(self):
        c = ClipInfo(index=1, source_path="x.mp4", duration=10.0)
        assert c.errors == []

    def test_optimized_paths_not_shared(self):
        a = ClipInfo(index=1, source_path="a.mp4", duration=5.0)
        b = ClipInfo(index=2, source_path="b.mp4", duration=5.0)
        a.optimized_paths["youtube"] = "/out/a_yt.mp4"
        assert "youtube" not in b.optimized_paths

    def test_errors_not_shared(self):
        a = ClipInfo(index=1, source_path="a.mp4", duration=5.0)
        b = ClipInfo(index=2, source_path="b.mp4", duration=5.0)
        a.errors.append("oops")
        assert b.errors == []


# ===========================================================================
# 5. RepurposeResult dataclass
# ===========================================================================

class TestRepurposeResult:
    def test_required_field(self):
        r = RepurposeResult(source_video="v.mp4")
        assert r.source_video == "v.mp4"

    def test_defaults(self):
        r = RepurposeResult(source_video="v.mp4")
        assert r.clips == []
        assert r.total_clips_created == 0
        assert r.total_clips_exported == 0
        assert r.total_clips_published == 0
        assert r.errors == []
        assert r.duration_seconds == 0.0

    def test_clips_not_shared(self):
        a = RepurposeResult(source_video="a.mp4")
        b = RepurposeResult(source_video="b.mp4")
        a.clips.append("x")
        assert b.clips == []


# ===========================================================================
# 6. RepurposeOrchestrator.__init__
# ===========================================================================

class TestOrchestratorInit:
    def test_default_init_no_config(self):
        with patch("repurpose_orchestrator.ro", None, create=True):
            with patch("config._get", return_value={}) as mock_get:
                # Force re-import is complex; just test with direct patch
                pass
        orch = RepurposeOrchestrator()
        assert orch._default_max_clips == 10
        assert orch._default_min_clip_duration == 15.0
        assert orch._default_max_clip_duration == 60.0
        assert orch._default_auto_publish is False
        assert orch._default_platforms == ["youtube", "tiktok", "instagram"]

    def test_init_reads_config_values(self):
        mock_config = {
            "max_clips": 5,
            "min_clip_duration": 10.0,
            "max_clip_duration": 45.0,
            "auto_publish": True,
            "platforms": ["youtube", "twitter"],
        }
        with patch("repurpose_orchestrator.SmartClipper", MagicMock()):
            with patch("config._get", return_value=mock_config):
                orch = RepurposeOrchestrator()
        assert orch._default_max_clips == 5
        assert orch._default_min_clip_duration == 10.0
        assert orch._default_max_clip_duration == 45.0
        assert orch._default_auto_publish is True
        assert orch._default_platforms == ["youtube", "twitter"]

    def test_init_config_exception_uses_defaults(self):
        with patch("config._get", side_effect=Exception("boom")):
            orch = RepurposeOrchestrator()
        assert orch._default_max_clips == 10
        assert orch._default_platforms == ["youtube", "tiktok", "instagram"]


# ===========================================================================
# Shared mock factory for orchestrator run() tests
# ===========================================================================

def _make_orchestrator_with_mocks(
    mock_smart_clipper=None,
    mock_export_optimizer=None,
    mock_content_publisher=None,
    mock_publish_job=None,
    mock_publish_result=None,
):
    """Patch module-level lazy imports and return a fresh orchestrator."""
    patches = {}
    if mock_smart_clipper is not None:
        patches["repurpose_orchestrator.SmartClipper"] = mock_smart_clipper
    if mock_export_optimizer is not None:
        patches["repurpose_orchestrator.ExportOptimizer"] = mock_export_optimizer
    if mock_content_publisher is not None:
        patches["repurpose_orchestrator.ContentPublisher"] = mock_content_publisher
    if mock_publish_job is not None:
        patches["repurpose_orchestrator.PublishJob"] = mock_publish_job
    if mock_publish_result is not None:
        patches["repurpose_orchestrator.PublishResult"] = mock_publish_result
    return patches


# ===========================================================================
# 7. run() — full happy path (auto_publish=True)
# ===========================================================================

class TestRunHappyPathAutoPublish:
    def test_full_pipeline(self, video_file, output_dir):
        # SmartClipper mock
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0), (30.0, 60.0)]
        mock_sc_inst.split_clips.return_value = [
            os.path.join(output_dir, "clip1.mp4"),
            os.path.join(output_dir, "clip2.mp4"),
        ]

        # ExportOptimizer mock
        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.side_effect = (
            lambda path, platform, out_dir: os.path.join(out_dir, f"opt_{platform}.mp4")
        )

        # Publisher mocks
        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pr = _make_publish_result("youtube", True)
        mock_pub_inst.publish.return_value = [mock_pr]

        mock_pj_cls = MagicMock()
        mock_pj_cls.side_effect = lambda **kw: MagicMock(**kw)

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=mock_pub_cls,
            PublishJob=mock_pj_cls,
        ):
            orch = RepurposeOrchestrator()
            cfg = RepurposeConfig(
                source_video=video_file,
                platforms=["youtube"],
                auto_publish=True,
                output_dir=output_dir,
            )
            result = orch.run(cfg)

        assert result.total_clips_created == 2
        assert result.total_clips_exported == 2
        assert result.total_clips_published == 2
        assert result.duration_seconds > 0

    def test_result_has_correct_clip_count(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 20.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.return_value = [_make_publish_result("youtube", True)]

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=lambda **kw: MagicMock(**kw)),
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    auto_publish=True,
                    output_dir=output_dir,
                )
            )

        assert len(result.clips) == 1
        assert result.clips[0].published is True


# ===========================================================================
# 8. run() — clips only (auto_publish=False)
# ===========================================================================

class TestRunClipsOnly:
    def test_auto_publish_false_does_not_call_publisher(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        mock_pub_cls = MagicMock()

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=mock_pub_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    auto_publish=False,
                    output_dir=output_dir,
                )
            )

        mock_pub_cls.return_value.publish.assert_not_called()
        assert result.total_clips_published == 0

    def test_clips_exported_without_publish(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 25.0), (25.0, 55.0)]
        mock_sc_inst.split_clips.return_value = [
            os.path.join(output_dir, "c1.mp4"),
            os.path.join(output_dir, "c2.mp4"),
        ]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    output_dir=output_dir,
                )
            )

        assert result.total_clips_created == 2
        assert result.total_clips_exported == 2


# ===========================================================================
# 9. run() — smart_clipper not available
# ===========================================================================

class TestRunSmartClipperUnavailable:
    def test_raises_runtime_error(self, video_file):
        with patch.multiple("repurpose_orchestrator", SmartClipper=None):
            orch = RepurposeOrchestrator()
            cfg = RepurposeConfig(source_video=video_file, platforms=["youtube"])
            with pytest.raises(RuntimeError, match="smart_clipper"):
                orch.run(cfg)


# ===========================================================================
# 10. run() — export_optimizer not available
# ===========================================================================

class TestRunExportOptimizerUnavailable:
    def test_raises_runtime_error(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = ["/tmp/clip.mp4"]

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=None,
        ):
            orch = RepurposeOrchestrator()
            cfg = RepurposeConfig(source_video=video_file, platforms=["youtube"])
            with pytest.raises(RuntimeError, match="export_optimizer"):
                orch.run(cfg)


# ===========================================================================
# 11. run() — publisher not available when auto_publish=True
# ===========================================================================

class TestRunPublisherUnavailable:
    def test_raises_runtime_error(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=None,
        ):
            orch = RepurposeOrchestrator()
            cfg = RepurposeConfig(
                source_video=video_file,
                platforms=["youtube"],
                auto_publish=True,
                output_dir=output_dir,
            )
            with pytest.raises(RuntimeError, match="publisher"):
                orch.run(cfg)


# ===========================================================================
# 12. run() — clip extraction returns empty (no scenes detected)
# ===========================================================================

class TestRunNoScenes:
    def test_returns_empty_result(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = []

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(source_video=video_file, platforms=["youtube"])
            )

        assert result.total_clips_created == 0
        assert result.clips == []
        assert result.errors == []

    def test_all_scenes_filtered_out(self, video_file):
        # All scenes are shorter than min_clip_duration=15s
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        # detect_scenes returns short scenes, split_clips returns []
        mock_sc_inst.detect_scenes.return_value = [(0.0, 5.0), (5.0, 10.0)]
        mock_sc_inst.split_clips.return_value = []

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    min_clip_duration=15.0,
                    max_clip_duration=60.0,
                )
            )

        # After filtering, no scenes pass the duration check
        assert result.total_clips_created == 0


# ===========================================================================
# 13. run() — clip extraction partial failure (exception during extraction)
# ===========================================================================

class TestRunClipExtractionFailure:
    def test_exception_during_clip_returns_error(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.side_effect = Exception("scenedetect boom")

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(source_video=video_file, platforms=["youtube"])
            )

        assert result.total_clips_created == 0
        assert any("scenedetect boom" in e for e in result.errors)


# ===========================================================================
# 14. run() — optimization failure for one platform (continues with others)
# ===========================================================================

class TestRunOptimizationPartialFailure:
    def test_one_platform_fails_others_succeed(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst

        def optimize_side_effect(path, platform, out_dir):
            if platform == "tiktok":
                raise RuntimeError("ffmpeg error for tiktok")
            return os.path.join(out_dir, f"opt_{platform}.mp4")

        mock_eo_inst.optimize_clip.side_effect = optimize_side_effect

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube", "tiktok"],
                    output_dir=output_dir,
                )
            )

        assert result.total_clips_created == 1
        clip = result.clips[0]
        assert "youtube" in clip.optimized_paths
        assert "tiktok" not in clip.optimized_paths
        assert any("tiktok" in e for e in clip.errors)


# ===========================================================================
# 15. run() — publish failure for one clip (continues with others)
# ===========================================================================

class TestRunPublishPartialFailure:
    def test_one_clip_publish_fails_others_succeed(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0), (30.0, 60.0)]
        clip1 = os.path.join(output_dir, "c1.mp4")
        clip2 = os.path.join(output_dir, "c2.mp4")
        mock_sc_inst.split_clips.return_value = [clip1, clip2]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        call_count = {"n": 0}

        def publish_side_effect(job):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("network error")
            return [_make_publish_result("youtube", True)]

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.side_effect = publish_side_effect

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=lambda **kw: MagicMock(**kw)),
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    auto_publish=True,
                    output_dir=output_dir,
                )
            )

        # Clip 1 failed, clip 2 succeeded
        assert result.total_clips_created == 2
        assert result.total_clips_published == 1


# ===========================================================================
# 16. _clip() — filters by duration, limits to max_clips
# ===========================================================================

class TestClipHelper:
    def test_filters_scenes_by_duration(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        # Two scenes: one in range, one too short
        mock_sc_inst.detect_scenes.return_value = [
            (0.0, 30.0),   # 30s — in range for min=15, max=60
            (30.0, 40.0),  # 10s — too short
        ]
        mock_sc_inst.split_clips.return_value = ["/tmp/c.mp4"]

        mock_cc = MagicMock(side_effect=lambda **kw: MagicMock(**kw))
        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ClipCandidate=mock_cc,
        ):
            orch = RepurposeOrchestrator()
            paths = orch._clip(video_file, max_clips=10, min_dur=15.0, max_dur=60.0)

        # Only 1 candidate passed to split_clips
        assert mock_sc_inst.split_clips.call_count == 1
        call_args = mock_sc_inst.split_clips.call_args
        candidates_passed = call_args[0][1]
        assert len(candidates_passed) == 1

    def test_limits_to_max_clips(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        # 5 scenes, max_clips=2
        mock_sc_inst.detect_scenes.return_value = [
            (i * 30.0, (i + 1) * 30.0) for i in range(5)
        ]
        mock_sc_inst.split_clips.return_value = ["/tmp/c1.mp4", "/tmp/c2.mp4"]

        mock_cc = MagicMock(side_effect=lambda **kw: MagicMock(**kw))
        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ClipCandidate=mock_cc,
        ):
            orch = RepurposeOrchestrator()
            paths = orch._clip(video_file, max_clips=2, min_dur=15.0, max_dur=60.0)

        candidates_passed = mock_sc_inst.split_clips.call_args[0][1]
        assert len(candidates_passed) == 2

    def test_returns_empty_when_no_scenes(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = []

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            paths = orch._clip(video_file, max_clips=5, min_dur=15.0, max_dur=60.0)

        assert paths == []
        mock_sc_inst.split_clips.assert_not_called()

    def test_raises_runtime_error_when_unavailable(self, video_file):
        with patch.multiple("repurpose_orchestrator", SmartClipper=None):
            orch = RepurposeOrchestrator()
            with pytest.raises(RuntimeError, match="smart_clipper"):
                orch._clip(video_file, 5, 15.0, 60.0)


# ===========================================================================
# 17. _optimize() — creates optimized files per platform
# ===========================================================================

class TestOptimizeHelper:
    def test_calls_optimize_clip_for_each_platform(self, output_dir):
        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        clip_paths = ["/tmp/clip1.mp4", "/tmp/clip2.mp4"]
        platforms = ["youtube", "tiktok"]

        with patch.multiple("repurpose_orchestrator", ExportOptimizer=mock_eo_cls):
            orch = RepurposeOrchestrator()
            clips = orch._optimize(clip_paths, platforms, output_dir)

        assert len(clips) == 2
        assert mock_eo_inst.optimize_clip.call_count == 4  # 2 clips × 2 platforms

    def test_clip_info_has_correct_optimized_paths(self, output_dir):
        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.side_effect = (
            lambda path, platform, out_dir: f"{out_dir}/{platform}_out.mp4"
        )

        with patch.multiple("repurpose_orchestrator", ExportOptimizer=mock_eo_cls):
            orch = RepurposeOrchestrator()
            clips = orch._optimize(["/tmp/c.mp4"], ["youtube", "tiktok"], output_dir)

        assert "youtube" in clips[0].optimized_paths
        assert "tiktok" in clips[0].optimized_paths

    def test_optimization_error_recorded_in_clip_info(self, output_dir):
        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.side_effect = Exception("ffmpeg crashed")

        with patch.multiple("repurpose_orchestrator", ExportOptimizer=mock_eo_cls):
            orch = RepurposeOrchestrator()
            clips = orch._optimize(["/tmp/c.mp4"], ["youtube"], output_dir)

        assert clips[0].optimized_paths == {}
        assert len(clips[0].errors) == 1
        assert "ffmpeg crashed" in clips[0].errors[0]

    def test_raises_runtime_error_when_unavailable(self, output_dir):
        with patch.multiple("repurpose_orchestrator", ExportOptimizer=None):
            orch = RepurposeOrchestrator()
            with pytest.raises(RuntimeError, match="export_optimizer"):
                orch._optimize(["/tmp/c.mp4"], ["youtube"], output_dir)

    def test_indexes_start_at_one(self, output_dir):
        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        with patch.multiple("repurpose_orchestrator", ExportOptimizer=mock_eo_cls):
            orch = RepurposeOrchestrator()
            clips = orch._optimize(
                ["/tmp/a.mp4", "/tmp/b.mp4", "/tmp/c.mp4"], ["youtube"], output_dir
            )

        assert [c.index for c in clips] == [1, 2, 3]


# ===========================================================================
# 18. _publish() — creates correct PublishJobs with title template
# ===========================================================================

class TestPublishHelper:
    def _make_clips_with_optimized(self, output_dir, count=2, platform="youtube"):
        clips = []
        for i in range(1, count + 1):
            c = ClipInfo(
                index=i,
                source_path=f"/tmp/c{i}.mp4",
                duration=30.0,
                optimized_paths={platform: os.path.join(output_dir, f"opt{i}.mp4")},
            )
            clips.append(c)
        return clips

    def test_publishes_each_clip(self, output_dir):
        clips = self._make_clips_with_optimized(output_dir, count=3)

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.return_value = [_make_publish_result("youtube", True)]

        mock_pj_cls = MagicMock()
        mock_pj_cls.side_effect = lambda **kw: MagicMock(**kw)

        with patch.multiple(
            "repurpose_orchestrator",
            ContentPublisher=mock_pub_cls,
            PublishJob=mock_pj_cls,
        ):
            orch = RepurposeOrchestrator()
            updated = orch._publish(
                clips, "Clip {index}", "", [], ["youtube"]
            )

        assert mock_pub_inst.publish.call_count == 3
        assert all(c.published for c in updated)

    def test_title_template_index_substitution(self, output_dir):
        clips = self._make_clips_with_optimized(output_dir, count=2)
        created_jobs = []

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.return_value = [_make_publish_result("youtube", True)]

        def capture_pj(**kw):
            obj = MagicMock(**kw)
            created_jobs.append(kw)
            return obj

        with patch.multiple(
            "repurpose_orchestrator",
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=capture_pj),
        ):
            orch = RepurposeOrchestrator()
            orch._publish(clips, "My Show Clip {index}", "", [], ["youtube"])

        titles = [j["title"] for j in created_jobs]
        assert "My Show Clip 1" in titles
        assert "My Show Clip 2" in titles

    def test_title_template_no_placeholder(self, output_dir):
        clips = self._make_clips_with_optimized(output_dir, count=1)
        created_jobs = []

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.return_value = [_make_publish_result("youtube", True)]

        def capture_pj(**kw):
            created_jobs.append(kw)
            return MagicMock(**kw)

        with patch.multiple(
            "repurpose_orchestrator",
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=capture_pj),
        ):
            orch = RepurposeOrchestrator()
            orch._publish(clips, "Static Title", "", [], ["youtube"])

        assert created_jobs[0]["title"] == "Static Title"

    def test_skips_clips_with_no_optimized_paths(self, output_dir):
        clip_no_opt = ClipInfo(index=1, source_path="/tmp/c.mp4", duration=30.0)

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst

        with patch.multiple(
            "repurpose_orchestrator",
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(),
        ):
            orch = RepurposeOrchestrator()
            updated = orch._publish([clip_no_opt], "T {index}", "", [], ["youtube"])

        mock_pub_inst.publish.assert_not_called()
        assert updated[0].published is False

    def test_publish_exception_recorded_in_errors(self, output_dir):
        clips = self._make_clips_with_optimized(output_dir, count=1)

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.side_effect = Exception("auth failure")

        with patch.multiple(
            "repurpose_orchestrator",
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=lambda **kw: MagicMock(**kw)),
        ):
            orch = RepurposeOrchestrator()
            updated = orch._publish(clips, "T {index}", "", [], ["youtube"])

        assert updated[0].published is False
        assert any("auth failure" in e for e in updated[0].errors)

    def test_raises_runtime_error_when_unavailable(self, output_dir):
        clips = self._make_clips_with_optimized(output_dir, count=1)
        with patch.multiple("repurpose_orchestrator", ContentPublisher=None):
            orch = RepurposeOrchestrator()
            with pytest.raises(RuntimeError, match="publisher"):
                orch._publish(clips, "T {index}", "", [], ["youtube"])


# ===========================================================================
# 19. Duration tracking
# ===========================================================================

class TestDurationTracking:
    def test_duration_seconds_set_on_empty_result(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = []

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(source_video=video_file, platforms=["youtube"])
            )

        assert result.duration_seconds >= 0.0

    def test_duration_seconds_set_on_full_pipeline(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    output_dir=output_dir,
                )
            )

        assert result.duration_seconds > 0.0

    def test_duration_set_even_when_extraction_fails(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.side_effect = Exception("crash")

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(source_video=video_file, platforms=["youtube"])
            )

        assert result.duration_seconds >= 0.0


# ===========================================================================
# 20. Error accumulation
# ===========================================================================

class TestErrorAccumulation:
    def test_optimize_errors_bubble_up_to_result(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.side_effect = Exception("encode fail")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    output_dir=output_dir,
                )
            )

        assert any("encode fail" in e for e in result.errors)

    def test_publish_errors_bubble_up_to_result(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        mock_pub_cls = MagicMock()
        mock_pub_inst = MagicMock()
        mock_pub_cls.return_value = mock_pub_inst
        mock_pub_inst.publish.side_effect = Exception("rate limited")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
            ContentPublisher=mock_pub_cls,
            PublishJob=MagicMock(side_effect=lambda **kw: MagicMock(**kw)),
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    auto_publish=True,
                    output_dir=output_dir,
                )
            )

        assert any("rate limited" in e for e in result.errors)

    def test_extraction_error_included_in_result_errors(self, video_file):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.side_effect = ValueError("bad video")

        with patch.multiple("repurpose_orchestrator", SmartClipper=mock_sc_cls):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(source_video=video_file, platforms=["youtube"])
            )

        assert any("bad video" in e for e in result.errors)

    def test_no_errors_on_clean_run(self, video_file, output_dir):
        mock_sc_cls = MagicMock()
        mock_sc_inst = MagicMock()
        mock_sc_cls.return_value = mock_sc_inst
        mock_sc_inst.detect_scenes.return_value = [(0.0, 30.0)]
        mock_sc_inst.split_clips.return_value = [os.path.join(output_dir, "c.mp4")]

        mock_eo_cls = MagicMock()
        mock_eo_inst = MagicMock()
        mock_eo_cls.return_value = mock_eo_inst
        mock_eo_inst.optimize_clip.return_value = os.path.join(output_dir, "opt.mp4")

        with patch.multiple(
            "repurpose_orchestrator",
            SmartClipper=mock_sc_cls,
            ExportOptimizer=mock_eo_cls,
        ):
            orch = RepurposeOrchestrator()
            result = orch.run(
                RepurposeConfig(
                    source_video=video_file,
                    platforms=["youtube"],
                    output_dir=output_dir,
                )
            )

        assert result.errors == []


# ===========================================================================
# 21. Constants sanity checks
# ===========================================================================

class TestConstants:
    def test_max_clips(self):
        assert _MAX_CLIPS == 20

    def test_supported_formats(self):
        assert ".mp4" in _SUPPORTED_FORMATS
        assert ".avi" in _SUPPORTED_FORMATS
        assert ".mov" in _SUPPORTED_FORMATS
        assert ".mkv" in _SUPPORTED_FORMATS
        assert ".webm" in _SUPPORTED_FORMATS

    def test_allowed_platforms(self):
        assert "youtube" in _ALLOWED_PLATFORMS
        assert "tiktok" in _ALLOWED_PLATFORMS
        assert "twitter" in _ALLOWED_PLATFORMS
        assert "instagram" in _ALLOWED_PLATFORMS

    def test_max_title_length(self):
        assert _MAX_TITLE_LENGTH == 500

    def test_max_description_length(self):
        assert _MAX_DESCRIPTION_LENGTH == 5000
