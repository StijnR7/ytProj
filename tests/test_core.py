"""Fast tests: python -m pytest tests"""
import numpy as np
import pytest

from ytfactory.claude_cli import extract_json
from ytfactory.pipeline import make_srt, shot_starts
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
    assert sc[1]["visual"]["type"] == "kinetic"  # comparison with <2 items degrades gracefully
    assert sc[2]["visual"]["camera"] in ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down")
    assert all(len(x["shots"]) == 1 for x in sc)  # old single-visual scenes become one shot
    assert word_count(s) == 5
    with pytest.raises(ValueError):
        validate_script({"chapters": [{"title": "x", "scenes": [{"narration": "a", "visual": {"type": "nope"}}]}]})


def test_shot_scripts_and_timing():
    script = {"chapters": [{"title": "A", "scenes": [{"mascot": "happy", "shots": [
        {"say": "The club moves fast.", "visual": {"type": "illustration", "prompt": "club"}, "fx": "shake"},
        {"say": "Faster than a bullet.", "visual": {"type": "kinetic", "text": "BULLET SPEED"}},
        {"say": "Look closer.", "visual": {"type": "closeup", "focus": "nope"}},
    ]}]}]}
    validate_script(script)
    s = normalize_script(script, "animals")
    sc = s["chapters"][0]["scenes"][0]
    assert sc["narration"] == "The club moves fast. Faster than a bullet. Look closer."
    assert sc["shots"][0]["fx"] == "shake" and sc["shots"][2]["visual"]["focus"] == "center"
    sentences = [{"text": "The club moves fast.", "start": 0.0, "end": 1.0},
                 {"text": "Faster than a bullet.", "start": 1.1, "end": 2.1},
                 {"text": "Look closer.", "start": 2.2, "end": 2.8}]
    starts = shot_starts(sc["shots"], sentences, sc["narration"])
    assert starts[0] == 0.0 and abs(starts[1] - 1.1) < 0.05 and abs(starts[2] - 2.2) < 0.05


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
        "closeup": {"focus": "left", "camera": "zoom_in"},
        "broll": {"query": "reef", "prefer": "any", "camera": "pan_left"},
        "kinetic": {"text": "10,000 TIMES GRAVITY"},
        "split": {"left": {"prompt": "a", "label": "Before"}, "right": {"prompt": "b", "label": "After"}},
    }
    spec = {"visual": {"type": kind, **visuals[kind]}, "mascot": "happy", "on_screen_text": "Label"}
    from PIL import Image
    img = Image.new("RGB", (400, 300), (40, 90, 160))
    ctx = SceneContext(size=(640, 360), duration=4.0, theme="history", envelope=np.ones(200, dtype=np.int8), image=img, image2=img)
    sc = make_scene(spec, ctx)
    for t in (0.0, 1.0, 3.9):
        f = sc.frame(t)
        assert f.size == (640, 360) and f.mode == "RGB"


def test_sequence_scene_with_fx():
    from PIL import Image
    img = Image.new("RGB", (400, 300), (200, 120, 60))
    shots = [
        {"spec": {"visual": {"type": "illustration", "prompt": "x", "camera": "zoom_in"}, "fx": "flash", "label": "Tag"}, "start": 0.0, "image": img, "image2": None},
        {"spec": {"visual": {"type": "kinetic", "text": "BOOM"}, "fx": "shake", "label": ""}, "start": 1.0, "image": img, "image2": None},
        {"spec": {"visual": {"type": "closeup", "focus": "right"}, "fx": "punch", "label": ""}, "start": 2.0, "image": img, "image2": None},
    ]
    ctx = SceneContext(size=(640, 360), duration=3.0, theme="space", shots=shots, envelope=np.ones(100, dtype=np.int8))
    sc = make_scene({"mascot": "surprised", "visual": shots[0]["spec"]["visual"]}, ctx)
    for t in (0.0, 0.1, 1.05, 2.1, 2.9):
        assert sc.frame(t).size == (640, 360)


def _longest_still(frames):
    from ytfactory.render.common import MotionAudit

    a = MotionAudit(30)
    for f in frames:
        a.add(f)
    return a.longest_seconds


def test_motion_audit_and_forced_motion():
    from PIL import Image

    from ytfactory.render.common import drift_camera, light_sweep

    flat = Image.new("RGB", (640, 360), (30, 60, 120))
    assert _longest_still([flat] * 150) > 4  # a frozen frame is detected
    forced = [light_sweep(drift_camera(flat, i / 30, 1, 2.0), i / 30) for i in range(150)]
    assert _longest_still(forced) < 2.5  # forced motion moves even a perfectly flat picture


@pytest.mark.parametrize("kind", ["title", "stat", "timeline", "list", "comparison", "quote", "mascot", "kinetic", "split", "archive"])
def test_no_scene_ever_freezes(kind):
    """Hard rule: nothing may be still for more than 3 seconds, even long after the entrance animations."""
    visuals = {
        "title": {"text": "Chapter", "subtitle": ""}, "stat": {"value": 5, "label": "x"},
        "timeline": {"events": [{"year": "1", "label": "a"}]}, "list": {"heading": "h", "items": ["a"]},
        "comparison": {"heading": "h", "items": [{"label": "a", "value": 1, "unit": ""}, {"label": "b", "value": 2, "unit": ""}]},
        "quote": {"text": "Hello.", "author": "A"}, "mascot": {"line": "Hi"}, "kinetic": {"text": "BOOM"},
        "split": {"left": {"prompt": "a", "label": "A"}, "right": {"prompt": "b", "label": "B"}},
        "archive": {"query": "x", "caption": "c"},
    }
    from PIL import Image

    img = Image.new("RGB", (400, 300), (90, 90, 90))
    ctx = SceneContext(size=(480, 270), duration=10.0, theme="brand", image=img, image2=img, seed=2)
    sc = make_scene({"visual": {"type": kind, **visuals[kind]}, "mascot": "none"}, ctx)
    assert _longest_still([sc.frame(i / 30) for i in range(120, 300)]) < 2.5
