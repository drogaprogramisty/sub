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

# Run tests
uv run pytest

# Lint/format with ruff
ruff check sub.py
ruff format sub.py
```

Always use `python3` (not `python`).

## System Requirements

- `ffmpeg` + `ffprobe` — video processing and subtitle burning: `brew install ffmpeg`

## Architecture

**Single file:** All code lives in `sub.py`.

**Key flow:**
1. `main()` → parses args, loads SRT via pysubs2, gets video dimensions (`ffprobe`, falls back to 1920x1080), builds ASS, burns subtitles
2. `build_ass()` → drops blank cues, groups word-level events, generates `SSAFile` with styled events
3. `burn_subtitles()` → calls `ffmpeg -vf ass=<tempfile>` with audio copy

**Grouping:** a new group starts when the current one reaches `max_words` or the gap between words exceeds `_PAUSE_THRESHOLD_MS` (300 ms).

**Subtitle modes:**
- **Static** (default): one dialogue line per group; entire group shown at once
- **Animated** (`--animated`): one dialogue line per word within each group; active word highlighted with `{\c<highlight>\3c&H000000&}word{\c&HFFFFFF&\3c&H000000&}`. Explicit color resets are used instead of `{\r}` so the per-group `{\fs\bord}` override survives. Multi-word cues get their duration split evenly across words.

**Vertical vs horizontal detection:**
- `height > width` → vertical video (TikTok-style): `MarginV = height / 3`
- Otherwise → horizontal: `MarginV = 60`

**`--position`** (`parse_position()`, presets in `POSITION_PRESETS`): when set, each event gets `{\an5\pos(width/2,y)}` so the block's centre sits at `position * height`; `_block_center_y()` estimates block height (`lines × fs × _LINE_HEIGHT_RATIO + 2 × border`) and clamps it inside `_SAFE_MARGIN_RATIO` (5%) of top/bottom. When unset (default), no `\an`/`\pos` is emitted and the MarginV layout above applies unchanged.

**Text layout (`_compute_text_layout()`):** per group, base font size is `_VERTICAL_FONT_RATIO` (0.08) × width for vertical or `_HORIZONTAL_FONT_RATIO` (0.08) × height for horizontal. Text width is estimated with `_CHAR_WIDTH_RATIO`; if one line doesn't fit within `_MARGIN_RATIO` side margins it wraps into two balanced lines (`_wrap_two_lines()`), and only scales the font down as a last resort (block height capped by `_MAX_BLOCK_HEIGHT_RATIO`). Applied as inline `{\fs..\bord..}` tags per event.

**ASS style:**
- Uses `pysubs2` for `SSAFile` / `SSAStyle` / `SSAEvent` construction
- `PlayResX/Y` set to actual video dimensions so `fontsize` maps 1:1 to pixels
- Colors: white primary, black outline, transparent background, no shadow
- Outline: `max(_MIN_BORDER, font_size * _BORDER_RATIO)` (min 4px, 7% of font size)
- Alignment: 2 (bottom-center, SSA numpad layout)

**Colors:** `color_to_ass_inline()` accepts names from `NAMED_COLORS` or `#RRGGBB`, converts to ASS BGR `&HBBGGRR&`; unknown values fall back to yellow.

**Constants:**
- `DEFAULT_FONT = "Helvetica Neue"`
- `DEFAULT_MAX_WORDS = 3`
- `DEFAULT_HIGHLIGHT_COLOR = "#00A6D6"`

**Output naming:**
- `video.mp4` → `video_sub.mp4`
- Collision-safe: appends `-1`, `-2`, etc. if output already exists
- Stdout only ever receives the output path; all messages go to stderr (`-q` silences them)
