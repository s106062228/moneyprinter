# Smart Clipping Architecture — Survey Summary
**Date**: 2026-03-27

## Proven Pipeline: Whisper + LLM + PySceneDetect

### Architecture Pattern (from AI-Youtube-Shorts-Generator, 3.2k stars)
1. Audio Extraction: FFmpeg converts video to WAV
2. Transcription: Whisper (GPU-accelerated) generates timestamped transcript
3. LLM Highlight Scoring: GPT/Ollama analyzes transcript, selects engaging segments
4. Scene Boundary Validation: PySceneDetect ensures clips start/end at natural scene cuts
5. Smart Cropping: Face detection (Haar Cascade) for centering
6. Subtitle Overlay: MoviePy + ImageMagick
7. Output: 9:16 vertical format clips

### PySceneDetect v0.6.7
- Three detectors: ContentDetector, ThresholdDetector, AdaptiveDetector
- Python API: scenedetect.detect(video_path, ContentDetector()) returns scene list
- EDL/OTIO export, threaded image export (50% perf gain)

### SupoClip (Open Source OpusClip Alternative)
- Stack: FastAPI + React + Redis + PostgreSQL + Docker
- LLM: Gemini, GPT, Claude, Ollama. Transcription: AssemblyAI
- AGPL-3.0, 326 stars

### MPV2 Strategy
- PySceneDetect for scene detection (no new deps)
- Existing STT (Whisper/AssemblyAI) for transcription
- Ollama LLM for engagement scoring (already configured)

## Sources
- https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator
- https://github.com/FujiwaraChoki/supoclip
- https://github.com/Breakthrough/PySceneDetect
- https://www.mdpi.com/2079-9292/14/18/3640
