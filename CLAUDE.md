# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file CLI tool for burning subtitles into video files. Takes a word-level SRT file and a video, groups words into display chunks, and burns styled subtitles using ffmpeg.

## Commands

```bash
# Install (editable — changes to sub.py take effect immediately, no reinstall needed)
uv tool install --editable .

# Run the CLI
python3 sub.py video.mp4 subtitles.srt

# Lint/format with ruff
ruff check sub.py
ruff format sub.py
```

Always use `python3` (not `python`).

## System Requirements

- `ffmpeg` — video processing and subtitle burning: `brew install ffmpeg`

## Architecture

**Single file:** All code lives in `sub.py`.

**Key flow:**
1. `main()` → parses args, loads SRT via pysubs2, gets video dimensions, builds ASS, burns subtitles
2. `build_ass()` → groups word-level events into chunks of `max_words`, generates `SSAFile` with styled events
3. `burn_subtitles()` → calls `ffmpeg -vf ass=<file>` with audio copy

**Subtitle modes:**
- **Static** (default): one dialogue line per group; entire group shown at once
- **Animated** (`--animated`): one dialogue line per word within each group; active word highlighted using `{\c&HBBGGRR&}word{\r}` inline ASS tags

**Vertical vs horizontal detection:**
- `height > width` → vertical video (TikTok-style): `MarginV = height / 3`
- Otherwise → horizontal: `MarginV = 60`

**ASS generation:**
- Uses `pysubs2` for clean `SSAFile` / `SSAStyle` / `SSAEvent` construction
- `PlayResX/Y` set to actual video dimensions so `fontsize` maps 1:1 to pixels
- Colors: white primary, black outline (3px), transparent background
- Alignment: 2 (bottom-center, SSA numpad layout)

**Constants:**
- `DEFAULT_FONT = "Helvetica Neue"`
- `DEFAULT_MAX_WORDS = 3`
- `DEFAULT_HIGHLIGHT_COLOR = "#00A6D6"`

**Font size:** Computed dynamically by `_compute_text_layout()` based on video dimensions (not a fixed constant). Base ratio is `_VERTICAL_FONT_RATIO = 0.08` of video width for vertical videos, or `_HORIZONTAL_FONT_RATIO = 0.08` of video height for horizontal videos.

**Output naming:**
- `video.mp4` → `video_sub.mp4`
- Collision-safe: appends `-1`, `-2`, etc. if output already exists
