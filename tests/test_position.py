"""Tests for --position (vertical placement of the subtitle block)."""

from __future__ import annotations

import argparse
import re

import pysubs2
import pytest

import sub

PORTRAIT = (1080, 1920)
LANDSCAPE = (1920, 1080)

# "extraordinarily incomprehensible" is too wide for one line, so it wraps to two
SHORT = ["this", "is", "fine"]
LONG = ["extraordinarily", "incomprehensible"]


def make_events(words: list[str]) -> list[pysubs2.SSAEvent]:
    events = []
    for i, w in enumerate(words):
        ev = pysubs2.SSAEvent()
        ev.start, ev.end, ev.text = i * 400, i * 400 + 350, w
        events.append(ev)
    return events


def build(words, size, animated=False, position=None, max_words=3):
    w, h = size
    return sub.build_ass(
        make_events(words),
        w,
        h,
        sub.DEFAULT_FONT,
        animated,
        sub.DEFAULT_HIGHLIGHT_COLOR,
        max_words,
        position,
    )


def pos_of(event: pysubs2.SSAEvent) -> tuple[int, int, int, int]:
    """Return (x, y, font_size, border) from an event's leading override block."""
    m = re.match(r"\{\\an5\\pos\((\d+),(\d+)\)\\fs(\d+)\\bord(\d+)\}", event.text)
    assert m, event.text
    return tuple(int(g) for g in m.groups())


def block_bounds(event: pysubs2.SSAEvent) -> tuple[float, float]:
    """Return (top, bottom) pixel extent of the block, including outline."""
    _, y, fs, bord = pos_of(event)
    n_lines = event.text.count(r"\N") + 1
    half = n_lines * fs * sub._LINE_HEIGHT_RATIO / 2 + bord
    return y - half, y + half


# --- default stays unchanged ---------------------------------------------------


@pytest.mark.parametrize("animated", [False, True])
@pytest.mark.parametrize(("size", "margin_v"), [(PORTRAIT, 1920 // 3), (LANDSCAPE, 60)])
def test_default_position_unchanged(size, margin_v, animated):
    ass = build(SHORT + LONG, size, animated=animated)
    style = ass.styles["Default"]
    assert style.alignment == 2
    assert style.marginv == margin_v
    for ev in ass.events:
        assert ev.text.startswith("{\\fs")
        assert "\\pos" not in ev.text and "\\an" not in ev.text


def test_default_position_exact_output():
    ass = build(SHORT + LONG, PORTRAIT)
    assert [ev.text for ev in ass.events] == [
        "{\\fs86\\bord6}this is fine",
        "{\\fs86\\bord6}extraordinarily\\Nincomprehensible",
    ]


# --- middle on 1080x1920 -------------------------------------------------------


@pytest.mark.parametrize("animated", [False, True])
@pytest.mark.parametrize("words", [SHORT, LONG])
def test_middle_portrait_is_centred(words, animated):
    ass = build(words, PORTRAIT, animated=animated, position=0.5)
    assert ass.events
    for ev in ass.events:
        x, y, _, _ = pos_of(ev)
        assert (x, y) == (540, 960)


def test_middle_portrait_multiline_centred_on_point():
    (ev,) = build(LONG, PORTRAIT, position=0.5).events
    assert r"\N" in ev.text
    top, bottom = block_bounds(ev)
    assert (top + bottom) / 2 == 960


def test_middle_preset_matches_float():
    assert sub.parse_position("middle") == 0.5
    a = build(SHORT, PORTRAIT, position=sub.parse_position("middle"))
    b = build(SHORT, PORTRAIT, position=0.5)
    assert [e.text for e in a.events] == [e.text for e in b.events]


# --- clamping at 0.0 and 1.0 ----------------------------------------------------


@pytest.mark.parametrize("animated", [False, True])
@pytest.mark.parametrize("words", [SHORT, LONG])
@pytest.mark.parametrize("size", [PORTRAIT, LANDSCAPE])
def test_clamped_at_top(size, words, animated):
    height = size[1]
    for ev in build(words, size, animated=animated, position=0.0).events:
        top, _ = block_bounds(ev)
        assert top == pytest.approx(height * 0.05, abs=1)


@pytest.mark.parametrize("animated", [False, True])
@pytest.mark.parametrize("words", [SHORT, LONG])
@pytest.mark.parametrize("size", [PORTRAIT, LANDSCAPE])
def test_clamped_at_bottom(size, words, animated):
    height = size[1]
    for ev in build(words, size, animated=animated, position=1.0).events:
        _, bottom = block_bounds(ev)
        assert bottom == pytest.approx(height * 0.95, abs=1)


# --- input validation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bottom", 0.85),
        ("lower", 0.75),
        ("middle", 0.5),
        ("top", 0.15),
        ("TOP", 0.15),
        ("0", 0.0),
        ("1", 1.0),
        ("0.62", 0.62),
    ],
)
def test_parse_position_valid(value, expected):
    assert sub.parse_position(value) == expected


@pytest.mark.parametrize("value", ["-0.1", "1.5", "nan", "inf"])
def test_parse_position_out_of_range(value):
    with pytest.raises(
        argparse.ArgumentTypeError, match="between 0.0 .top. and 1.0 .bottom."
    ):
        sub.parse_position(value)


def test_parse_position_unknown_preset():
    with pytest.raises(
        argparse.ArgumentTypeError, match="one of: bottom, lower, middle, top"
    ):
        sub.parse_position("center")
