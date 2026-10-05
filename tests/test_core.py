"""Fast tests: python -m pytest tests"""
import numpy as np
import pytest

from ytfactory.claude_cli import extract_json
from ytfactory.pipeline import make_srt
from ytfactory.project import normalize_script, slugify, theme_for, validate_script, word_count
from ytfactory.render.audio import ambient_music, mouth_envelope
from ytfactory.render.mascot import EXPRESSIONS, draw_zib
from ytfactory.render.scenes import SCENES, SceneContext, make_scene
from ytfactory.tts import split_sentences


def test_extract_json_variants():
    assert extract_json('Sure!\n```json\n{"a": 1,}\n```') == {"a": 1}
    assert extract_json('blah {"b": [1, 2]} blah') == {"b": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_split_sentences():
    s = split_sentences("Dr. Smith arrived. It was 1453! Was it? Yes, it was.")
    assert s[0].startswith("Dr. Smith")
    assert len(s) >= 3


def test_slug_and_theme():
    assert slugify("What If the Moon Disappeared?!") == "what-if-the-moon-disappeared"
    assert theme_for("Interesting Animals") == "animals"
    assert theme_for("hypotheticals") == "hypotheticals"
    assert theme_for("cooking") == "brand"


SCRIPT = {"chapters": [{"title": "A", "scenes": [
    {"narration": "Hello there world.", "visual": {"type": "stat", "value": "1,200", "label": "x"}, "mascot": "bogus"},
    {"narration": "Two.", "visual": {"type": "comparison", "items": [{"label": "a", "value": 1}]}},
    {"narration": "Three.", "visual": {"type": "illustration", "prompt": "p", "camera": "spin"}},
]}]}


def test_validate_and_normalize():
    validate_script(SCRIPT)
    s = normalize_script(SCRIPT, "space")
    sc = s["chapters"][0]["scenes"]
    assert sc[0]["visual"]["value"] == 1200.0 and sc[0]["mascot"] == "none"
    assert sc[1]["visual"]["type"] == "mascot"  # comparison with <2 items degrades gracefully
    assert sc[2]["visual"]["camera"] == "zoom_in"
    assert word_count(s) == 5
    with pytest.raises(ValueError):
        validate_script({"chapters": [{"title": "x", "scenes": [{"narration": "a", "visual": {"type": "nope"}}]}]})


def test_srt():
    tl = {"scenes": [{"start": 10.0, "sentences": [{"text": "word " * 30, "start": 0.2, "end": 6.2}]}]}
    srt = make_srt(tl)
    assert srt.startswith("1\n00:00:10,200 --> ")
    assert "2\n" in srt  # long sentence split into several cues


def test_mascot_all_expressions():
    for e in EXPRESSIONS:
        img = draw_zib(120, e, mouth=2)
        assert img.size == (120, 132) and img.getbbox()


def test_audio_helpers():
    env = mouth_envelope(np.sin(np.linspace(0, 400, 24000)).astype(np.float32), 24000, 30, 30)
    assert env.max() <= 4 and len(env) == 30
    m = ambient_music(3.0, "space", sr=8000)
    assert len(m) == 24000 and np.abs(m).max() <= 0.51


@pytest.mark.parametrize("kind", list(SCENES))
def test_every_scene_renders(kind):
    visuals = {
        "illustration": {"prompt": "x", "camera": "pan_left"},
        "archive": {"query": "x", "caption": "A caption"},
        "title": {"text": "Chapter title here", "subtitle": "sub"},
        "stat": {"value": 12345, "suffix": " km", "label": "label", "decimals": 0},
        "timeline": {"events": [{"year": "1", "label": "a"}, {"year": "2", "label": "b"}]},
        "list": {"heading": "h", "items": ["a", "b", "c"]},
        "comparison": {"heading": "h", "items": [{"label": "a", "value": 1, "unit": "m"}, {"label": "b", "value": 1000, "unit": "m"}]},
        "quote": {"text": "To be or not.", "author": "Someone"},
        "mascot": {"line": "Hi!"},
    }
    spec = {"visual": {"type": kind, **visuals[kind]}, "mascot": "happy", "on_screen_text": "Label"}
    ctx = SceneContext(size=(640, 360), duration=4.0, theme="history", envelope=np.ones(200, dtype=np.int8))
    sc = make_scene(spec, ctx)
    for t in (0.0, 1.0, 3.9):
        f = sc.frame(t)
        assert f.size == (640, 360) and f.mode == "RGB"
