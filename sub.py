#!/usr/bin/env python3
"""Burn subtitles into video files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import pysubs2

try:
    __version__ = _pkg_version("sub-cli")
except PackageNotFoundError:
    __version__ = "1.0.0"

# Defaults
DEFAULT_FONT = "Helvetica Neue"
DEFAULT_MAX_WORDS = 3
DEFAULT_HIGHLIGHT_COLOR = "#00A6D6"  # previous default: "yellow"

# Auto font-size tuning
_MARGIN_RATIO = 0.05  # safe margin on each horizontal side
_MAX_BLOCK_HEIGHT_RATIO = 0.30  # subtitle block must not exceed this fraction of height
# estimated char width as fraction of font size (Helvetica Neue)
_CHAR_WIDTH_RATIO = 0.55
_LINE_HEIGHT_RATIO = 1.3  # line height as fraction of font size
# base font size as fraction of video width (vertical/portrait)
_VERTICAL_FONT_RATIO = 0.08
# base font size as fraction of video height (horizontal/landscape)
_HORIZONTAL_FONT_RATIO = 0.08
_BORDER_RATIO = 0.07  # outline thickness as fraction of font size
_MIN_BORDER = 4  # minimum outline thickness in pixels
_PAUSE_THRESHOLD_MS = 300  # gap (ms) between words that forces a new subtitle group
_SAFE_MARGIN_RATIO = 0.05  # --position: block is clamped this far from top/bottom edges

# --position presets: vertical centre of the subtitle block as a fraction of height
POSITION_PRESETS: dict[str, float] = {
    "bottom": 0.85,
    "lower": 0.75,
    "middle": 0.5,
    "top": 0.15,
}

# Named colors: (R, G, B) for converting to ASS BGR inline tag
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "green": (0, 255, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "orange": (255, 128, 0),
    "magenta": (255, 0, 255),
    "black": (0, 0, 0),
}


def color_to_ass_inline(color: str) -> str:
    """Convert a color name or #RRGGBB hex string to ASS \\c inline tag value.

    ASS uses BGR byte order: &HBBGGRR&
    """
    lower = color.lower()
    if lower in NAMED_COLORS:
        r, g, b = NAMED_COLORS[lower]
        return f"&H{b:02X}{g:02X}{r:02X}&"

    m = re.match(r"#?([0-9a-fA-F]{6})$", color)
    if m:
        h = m.group(1)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"&H{b:02X}{g:02X}{r:02X}&"

    return "&H00FFFF&"  # fallback: yellow


def _wrap_two_lines(text: str) -> str:
    """Split text at the word boundary that produces the most balanced two lines."""
    words = text.split()
    if len(words) <= 1:
        return text
    best_split, best_diff = 1, float("inf")
    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])
        diff = abs(len(line1) - len(line2))
        if diff < best_diff:
            best_diff, best_split = diff, i
    return " ".join(words[:best_split]) + r"\N" + " ".join(words[best_split:])


def _compute_text_layout(
    text: str, width: int, height: int, is_vertical: bool
) -> tuple[int, str]:
    """Return (font_size, display_text) sized to fit within safe screen margins.

    Tries a single line first; wraps to two balanced lines if needed; scales
    the font down only as a last resort.
    """
    available_width = width * (1 - 2 * _MARGIN_RATIO)
    max_block_height = height * _MAX_BLOCK_HEIGHT_RATIO

    base = int(
        width * _VERTICAL_FONT_RATIO if is_vertical else height * _HORIZONTAL_FONT_RATIO
    )

    def text_px(t: str, size: int) -> float:
        return len(t) * size * _CHAR_WIDTH_RATIO

    # Single line fits at base size?
    if text_px(text, base) <= available_width:
        return base, text

    # Two lines at base size?
    wrapped = _wrap_two_lines(text)
    lines = wrapped.split(r"\N")
    longest = max(lines, key=len)
    two_line_height = base * _LINE_HEIGHT_RATIO * 2
    if (
        text_px(longest, base) <= available_width
        and two_line_height <= max_block_height
    ):
        return base, wrapped

    # Scale down to fit two lines
    size_from_width = available_width / (len(longest) * _CHAR_WIDTH_RATIO)
    size_from_height = max_block_height / (_LINE_HEIGHT_RATIO * 2)
    return int(min(size_from_width, size_from_height)), wrapped


def parse_position(value: str) -> float:
    """Parse --position: a preset name or a float from 0.0 (top) to 1.0 (bottom)."""
    key = value.strip().lower()
    if key in POSITION_PRESETS:
        return POSITION_PRESETS[key]
    presets = ", ".join(POSITION_PRESETS)
    try:
        position = float(key)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid position {value!r}: use a number from 0.0 (top) to 1.0 (bottom) "
            f"or one of: {presets}"
        ) from None
    if not 0.0 <= position <= 1.0:  # also rejects nan
        raise argparse.ArgumentTypeError(
            f"position {value} is out of range: must be between 0.0 (top) and 1.0 (bottom)"
        )
    return position


def _block_center_y(
    position: float, n_lines: int, font_size: int, border: int, height: int
) -> int:
    """Return the y pixel for the centre of the subtitle block.

    The block is centred on position * height, then clamped so that every line
    (including its outline) stays inside a _SAFE_MARGIN_RATIO margin.
    """
    half_block = n_lines * font_size * _LINE_HEIGHT_RATIO / 2 + border
    safe = height * _SAFE_MARGIN_RATIO
    lowest, highest = safe + half_block, height - safe - half_block
    if lowest > highest:  # block taller than the safe area; centre it
        return height // 2
    return round(min(max(position * height, lowest), highest))


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream. Falls back to 1920x1080."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "v:0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return 1920, 1080


def build_ass(
    events: list[pysubs2.SSAEvent],
    width: int,
    height: int,
    font: str,
    animated: bool,
    highlight_color: str,
    max_words: int,
    position: float | None = None,
) -> pysubs2.SSAFile:
    """Build an ASS subtitle file from word-level SRT events.

    Groups consecutive events into chunks of max_words. In static mode each
    group renders as a single subtitle line. In animated mode each word within
    the group gets its own dialogue line where that word is highlighted and the
    rest are shown in the default color.

    position (0.0 top .. 1.0 bottom) centres each block on that fraction of the
    height via {\\an5\\pos}; None keeps the default bottom-anchored MarginV layout.
    """
    is_vertical = height > width
    margin_v = height // 3 if is_vertical else 60

    output = pysubs2.SSAFile()
    output.info["PlayResX"] = str(width)
    output.info["PlayResY"] = str(height)

    base_font_size = int(
        width * _VERTICAL_FONT_RATIO if is_vertical else height * _HORIZONTAL_FONT_RATIO
    )

    style = pysubs2.SSAStyle()
    style.fontname = font
    style.fontsize = base_font_size
    style.primarycolor = pysubs2.Color(255, 255, 255, 0)  # white, opaque
    style.outlinecolor = pysubs2.Color(0, 0, 0, 0)  # black outline
    style.backcolor = pysubs2.Color(0, 0, 0, 255)  # fully transparent bg
    style.outline = max(_MIN_BORDER, int(base_font_size * _BORDER_RATIO))
    style.shadow = 0
    style.alignment = 2  # bottom-center (SSA numpad layout)
    style.marginv = margin_v
    output.styles["Default"] = style

    highlight_tag = color_to_ass_inline(highlight_color)

    # Drop blank cues before grouping (Whisper occasionally emits empty segments)
    events = [e for e in events if e.text.strip()]

    # Group word-level events into display chunks, splitting on max_words or long pauses
    groups: list[list[pysubs2.SSAEvent]] = []
    current: list[pysubs2.SSAEvent] = []
    for event in events:
        if current:
            gap = event.start - current[-1].end
            if len(current) >= max_words or gap > _PAUSE_THRESHOLD_MS:
                groups.append(current)
                current = []
        current.append(event)
    if current:
        groups.append(current)

    for group in groups:
        words = [e.text.strip() for e in group]
        group_end = group[-1].end
        group_text = " ".join(words)

        font_size, display_text = _compute_text_layout(
            group_text, width, height, is_vertical
        )
        border = max(_MIN_BORDER, int(font_size * _BORDER_RATIO))
        fs_tag = f"{{\\fs{font_size}\\bord{border}}}"
        if position is not None:
            n_lines = display_text.count(r"\N") + 1
            y = _block_center_y(position, n_lines, font_size, border, height)
            fs_tag = f"{{\\an5\\pos({width // 2},{y})\\fs{font_size}\\bord{border}}}"

        if not animated:
            ev = pysubs2.SSAEvent()
            ev.start = group[0].start
            ev.end = group_end
            ev.text = fs_tag + display_text
            output.events.append(ev)
        else:
            # In animated mode we need {\fs} to survive across highlighted words.
            # Use explicit color resets instead of {\r} so the font-size override persists.

            # Expand each cue into word-level (word, start, end) tuples.
            # Multi-word cues have their duration distributed evenly across words.
            word_timings: list[tuple[str, int, int]] = []
            for cue in group:
                cue_words = cue.text.strip().split()
                n = len(cue_words)
                if not n:
                    continue
                duration = cue.end - cue.start
                slot = duration // n
                for j, w in enumerate(cue_words):
                    w_start = cue.start + j * slot
                    w_end = cue.start + (j + 1) * slot if j < n - 1 else cue.end
                    word_timings.append((w, w_start, w_end))

            for i, (_, win_start, _) in enumerate(word_timings):
                win_end = (
                    word_timings[i + 1][1] if i + 1 < len(word_timings) else group_end
                )

                word_idx = 0
                line_strings = []
                for line in display_text.split(r"\N"):
                    line_parts = []
                    for w in line.split():
                        if word_idx == i:
                            # \3c locks outline to black; explicit white restore keeps \fs alive
                            line_parts.append(
                                f"{{\\c{highlight_tag}\\3c&H000000&}}{w}"
                                f"{{\\c&HFFFFFF&\\3c&H000000&}}"
                            )
                        else:
                            line_parts.append(w)
                        word_idx += 1
                    line_strings.append(" ".join(line_parts))

                ev = pysubs2.SSAEvent()
                ev.start = win_start
                ev.end = win_end
                ev.text = fs_tag + r"\N".join(line_strings)
                output.events.append(ev)

    return output


def get_unique_output_path(base_path: Path) -> Path:
    """Return base_path, or base_path with -N suffix if it already exists."""
    if not base_path.exists():
        return base_path
    stem, suffix, parent = base_path.stem, base_path.suffix, base_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def burn_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    quiet: bool,
) -> bool:
    """Run ffmpeg to burn ASS subtitles into the video."""
    # Escape colons in path for ffmpeg filter graph syntax (Windows safety; no-op on macOS)
    ass_str = str(ass_path).replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg",
        "-v",
        "quiet" if quiet else "warning",
        "-i",
        str(video_path),
        "-vf",
        f"ass={ass_str}",
        "-c:a",
        "copy",
        "-y",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        if not quiet:
            print(f"Error: ffmpeg failed: {e}", file=sys.stderr)
        return False
    except FileNotFoundError:
        if not quiet:
            print(
                "Error: ffmpeg not found. Install it (macOS: brew install ffmpeg, "
                "Debian/Ubuntu: sudo apt install ffmpeg) or see https://ffmpeg.org/download.html",
                file=sys.stderr,
            )
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Burn subtitles into a video file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  sub video.mp4 subtitles.srt
  sub video.mp4 subtitles.srt --animated
  sub video.mp4 subtitles.srt --animated --highlight-color cyan
  sub video.mp4 subtitles.srt --max-words 5 --font Arial
  sub video.mp4 subtitles.srt --position lower     # solo vertical podcast short
  sub video.mp4 subtitles.srt --position middle    # split-screen: between the two faces
  sub video.mp4 subtitles.srt --position 0.6
  sub video.mp4 subtitles.srt -o output.mp4 -q
""",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("video", help="Input video file")
    parser.add_argument("srt", help="Word-level SRT subtitle file")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output video path (default: <video>_sub.<ext>)",
    )
    parser.add_argument(
        "--font",
        type=str,
        default=DEFAULT_FONT,
        help=f"Font name (default: {DEFAULT_FONT!r})",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=DEFAULT_MAX_WORDS,
        help=f"Words shown on screen at once (default: {DEFAULT_MAX_WORDS})",
    )
    parser.add_argument(
        "--animated",
        action="store_true",
        help="Highlight the currently active word",
    )
    parser.add_argument(
        "--highlight-color",
        type=str,
        default=DEFAULT_HIGHLIGHT_COLOR,
        help=f"Highlight color for animated mode — name or #RRGGBB (default: {DEFAULT_HIGHLIGHT_COLOR!r})",
    )
    parser.add_argument(
        "--position",
        type=parse_position,
        default=None,
        metavar="POS",
        help=(
            "Vertical centre of the subtitle block: 0.0 (top) to 1.0 (bottom), or a preset "
            + ", ".join(f"{k}={v}" for k, v in POSITION_PRESETS.items())
            + ". Clamped to stay 5%% inside the frame. (default: bottom edge at 2/3 of the "
            "height for vertical video, 60px above the bottom for horizontal)"
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all output except the output file path",
    )

    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    srt_path = Path(args.srt).resolve()

    if not video_path.exists():
        if not args.quiet:
            print(f"Error: Video file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    if not srt_path.exists():
        if not args.quiet:
            print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        base = video_path.parent / f"{video_path.stem}_sub{video_path.suffix}"
        output_path = get_unique_output_path(base)

    if not args.quiet:
        print(f"Processing {video_path.name}...", file=sys.stderr)

    try:
        subs = pysubs2.load(str(srt_path))
    except Exception as e:  # noqa: BLE001 — any load failure is reported, not raised
        if not args.quiet:
            print(f"Error: Failed to load SRT: {e}", file=sys.stderr)
        sys.exit(1)

    if not subs.events:
        if not args.quiet:
            print("Error: No subtitle events found in SRT file", file=sys.stderr)
        sys.exit(1)

    width, height = get_video_dimensions(video_path)

    ass_file = build_ass(
        subs.events,
        width,
        height,
        args.font,
        args.animated,
        args.highlight_color,
        args.max_words,
        args.position,
    )

    # Write ASS to a temp file, burn into video, then clean up
    fd, ass_path_str = tempfile.mkstemp(suffix=".ass", prefix="sub_")
    os.close(fd)
    ass_path = Path(ass_path_str)
    try:
        ass_file.save(str(ass_path), format_="ass")
        if burn_subtitles(video_path, ass_path, output_path, args.quiet):
            print(output_path)
        else:
            sys.exit(1)
    finally:
        ass_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
