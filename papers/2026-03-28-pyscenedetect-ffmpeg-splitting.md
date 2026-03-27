# PySceneDetect FFmpeg Video Splitting API

## Summary
PySceneDetect v0.6.7 includes built-in `split_video_ffmpeg()` for splitting videos at scene boundaries.

## API: split_video_ffmpeg()
- `input_video_path` (str): Source video
- `scene_list` (List[Tuple[FrameTimecode, FrameTimecode]]): Start/end for each scene
- `output_dir` (Path|None): Destination folder
- `output_file_template` (str): Pattern with $VIDEO_NAME, $SCENE_NUMBER, $START_TIME, $END_TIME
- `arg_override` (str): Custom ffmpeg encoding params
- `show_progress` (bool): tqdm progress bar
- Returns: int (0 = success)
- Default: uses codec='copy' for fast lossless extraction

## Integration with SmartClipper
SmartClipper returns ClipCandidate(start_time, end_time, score, transcript).
Conversion: ClipCandidate → (FrameTimecode(start), FrameTimecode(end)) → scene_list.
Then call split_video_ffmpeg(video_path, scene_list, output_dir).

## Source
- https://www.scenedetect.com/docs/latest/api/video_splitter.html
- https://github.com/Breakthrough/PySceneDetect
