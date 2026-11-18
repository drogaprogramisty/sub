# sub - burn TikTok-style subtitles into videos

> [!NOTE]
> Also: Optimised for agentic usage with Claude Code, Codex, Open Code and more!

Takes a video and a **word-level** SRT file, groups words into short on-screen chunks and burns styled subtitles directly into the video frames with ffmpeg.

- **Static mode** (default): a group of words appears at once, then the next group
- **Animated mode** (`--animated`): the currently spoken word is highlighted (karaoke-style)
- Auto-detects vertical (9:16) vs horizontal video and positions subtitles accordingly
- Font size is computed from video dimensions; long lines wrap into two balanced lines
- A pause between words (>300 ms) starts a new subtitle group
- Audio is copied without re-encoding

## Requirements

- Python 3.9+
- ffmpeg + ffprobe (`brew install ffmpeg`)
- uv (`brew install uv` or [see official docs](https://docs.astral.sh/uv/getting-started/installation/))

Tested on macOS. Linux / Windows — *not tested*. The default font is `Helvetica Neue` (bundled with macOS); on other systems pass a font you have installed, e.g. `--font "DejaVu Sans"`, otherwise libass falls back to a system default.

## Installation

```bash
uv pip install --system git+https://github.com/drogaprogramisty/sub
```

## Usage

```bash
sub video.mp4 subtitles.srt                                  # Creates video_sub.mp4
sub video.mp4 subtitles.srt --animated                       # Highlight the active word
sub video.mp4 subtitles.srt --animated --highlight-color cyan
sub video.mp4 subtitles.srt --max-words 5 --font Arial       # 5 words on screen at once
sub video.mp4 subtitles.srt -o output.mp4 -q                 # Custom output, quiet mode
sub -h                                                       # All options
```

If `video_sub.mp4` already exists, `video_sub-1.mp4`, `video_sub-2.mp4`, ... are used.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--animated` | off | Highlight the currently spoken word |
| `--highlight-color COLOR` | `#00A6D6` | Highlight color — name or `#RRGGBB` |
| `--max-words N` | `3` | Max words shown on screen at once |
| `--font FONT` | `Helvetica Neue` | Font name |
| `-o OUTPUT` | `<video>_sub.<ext>` | Output video path |
| `-q` | off | Quiet mode, only prints output path (for CLI/agent usage) |

Named colors: `white`, `yellow`, `cyan`, `green`, `red`, `blue`, `orange`, `magenta`, `black`.

## Full pipeline: transcribe → burn

No SRT yet? Generate a word-level one with [stt](https://github.com/drogaprogramisty/stt) (Apple Silicon):

```bash
stt video.mp4 -f srt --words          # Creates video.srt with one word per entry
sub video.mp4 video.srt --animated    # Creates video_sub.mp4
```

`--words` matters — `sub` relies on per-word timing for grouping and highlighting.

## CLAUDE.md / AGENTS.md

Example plug-and-play .md paragraph so your favorite agent can use this tool:

```markdown
## sub - Burn subtitles into video

Burn word-level SRT subtitles into a video (TikTok-style). Generate the SRT with `stt video.mp4 -f srt --words`.

sub video.mp4 video.srt                          # Creates video_sub.mp4
sub video.mp4 video.srt --animated               # Highlight the active word
sub video.mp4 video.srt --highlight-color cyan   # Highlight color: name or #RRGGBB
sub video.mp4 video.srt --max-words 5            # Words on screen at once (default 3)
sub video.mp4 video.srt --font Arial             # Custom font
sub video.mp4 video.srt -o out.mp4 -q            # Custom output path, quiet mode (prints output path only)
sub -h                                           # for help / all options
```
