"""Prompt templates. This is where the channel's voice and quality bar live."""
from __future__ import annotations

import json

from .config import load_config


def channel_bible() -> str:
    ch = load_config()["channel"]
    return f"""CHANNEL: "{ch['name']}" ({ch['handle']}) - tagline: "{ch['tagline']}"
NARRATOR: {ch['mascot_name']}, a tiny floating exploration probe with a screen for a face. {ch['mascot_name']} is
curious, warm, a little cheeky, endlessly fascinated, and explains things like a brilliant friend at 2am.
{ch['mascot_name']} narrates in first person occasionally ("when I first probed into this...") but the topic is always the star.
AUDIENCE: curious adults and teens worldwide, English, no prior knowledge assumed, but never talked down to.
PILLARS: history, space, interesting animals, hypotheticals ("what if...").

VOICE RULES
- Conversational, vivid and precise. Short sentences mixed with longer ones. Active voice.
- Concrete over abstract: real numbers, names, dates, places, and relatable comparisons
  ("as heavy as 30 school buses", "if Earth were a basketball...").
- Light humor and wonder; never snarky about real victims or tragedies.
- No filler: never say "in this video", "without further ado", "let's dive in", "buckle up", "smash that like button".
- Accuracy first: only state facts you are confident are true. Flag disputed points ("historians still argue about...").
  For hypotheticals, ground every step in real science and clearly label speculation.
"""


SCENE_TYPES_DOC = """SCENE VISUAL TYPES (every scene has exactly one "visual"):
- {"type":"illustration","prompt":"...","camera":"zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down"}
    An AI-generated flat illustration. "prompt" = a concrete visual description for an image model:
    subject, setting, composition, lighting, mood, 15-40 words. Never ask for text/letters in the image.
    Do not name real living people. Generic historical figures are fine ("a Byzantine emperor on a throne").
- {"type":"archive","query":"...","caption":"...","prompt":"..."}
    A REAL public-domain/CC image from Wikimedia Commons: famous portraits, paintings, maps, artifacts,
    NASA/ESA photos, real animal photos. "query" = precise Commons search terms (e.g. "Mehmed II portrait Bellini",
    "Hubble Pillars of Creation", "axolotl Ambystoma mexicanum"). "caption" = short museum-style label
    ("Mehmed II, painted by Gentile Bellini, 1480"). "prompt" = illustration fallback if nothing is found.
- {"type":"title","text":"...","subtitle":"..."}  Chapter title card. Use as the FIRST scene of each chapter except the first.
- {"type":"stat","value":12345,"prefix":"","suffix":" km","label":"...","decimals":0}  A big animated number.
- {"type":"timeline","events":[{"year":"1453","label":"max 5 words"}, ...]}  3-6 events, in order.
- {"type":"list","heading":"...","items":["max 6 words", ...]}  2-5 items revealed one by one.
- {"type":"comparison","heading":"...","items":[{"label":"...","value":123,"unit":"m"}, ...]}  2-5 bars to compare sizes/amounts.
- {"type":"quote","text":"...","author":"..."}  A real, verified quote only (or a clearly labelled paraphrase).
- {"type":"mascot","line":"..."}  Zib on screen talking to the viewer with a speech bubble (max 12 words).
    Use for jokes, rhetorical questions, "wait, what?" moments and pattern interrupts.

Optional per scene:
- "mascot": "none|happy|surprised|thinking|excited|worried|pointing"  -> Zib pops into the corner reacting.
- "on_screen_text": short label (max 6 words) shown over illustrations, e.g. a name, place or date.
- "theme": "space|history|animals|hypotheticals|brand" -> background style for graphic scenes (defaults to the video's category).
"""


def ideas_prompt(n: int, categories: list[str], existing: list[str]) -> str:
    ex = "\n".join(f"- {t}" for t in existing[-150:]) or "(none yet)"
    return f"""{channel_bible()}

TASK: Brainstorm {n} video ideas for this channel. Mix the pillars: {', '.join(categories)}.
Each video will be a 10-14 minute narrated, animated documentary.

Great ideas for this channel:
- Have a surprising hook or a question people genuinely wonder about (high curiosity gap).
- Have enough real depth for 12 minutes (a story arc, not a single fact).
- Work visually with illustrations, archive images, stats and timelines.
- Are evergreen (still interesting in 5 years), and have proven search/browse demand.
- Mix formats: epic historical stories, "what if" thought experiments, extreme animals,
  scale-of-the-universe pieces, mysteries, "how did people survive...", "the weirdest...".

Avoid repeating or closely overlapping these existing videos:
{ex}

Return ONLY JSON in a ```json block:
{{"ideas":[{{"title":"YouTube-ready title, max 60 chars","category":"one of {categories}",
"angle":"1-2 sentences: what makes our take compelling","hook":"the first line Zib would say",
"why_it_works":"short reason it will get clicks and watch time"}}]}}
"""


def research_prompt(topic: str, category: str, angle: str = "") -> str:
    return f"""{channel_bible()}

TASK: Research the topic below for a 12-minute documentary and produce a research brief.
TOPIC: {topic}
CATEGORY: {category}
{('ANGLE: ' + angle) if angle else ''}

Use web search to verify facts if available. The brief must contain:
1. The core story/arc in 5-8 beats (what makes this gripping from start to finish).
2. 25-40 verified key facts: names, dates, numbers, places. Mark anything disputed as [DISPUTED] and anything
   you could not verify as [UNVERIFIED].
3. 6-10 "wow" details that would make a viewer say "wait, what?".
4. Common misconceptions and the truth.
5. Good visual opportunities: famous paintings/photos/artifacts that exist on Wikimedia Commons
   (give exact names), and scenes that would make great illustrations.
6. Numbers worth turning into stats, comparisons or timelines.
7. 5-10 reputable sources (URLs) used.

Write the brief in Markdown. Be thorough but dense - no padding.
"""


def script_prompt(topic: str, category: str, research: str, target_words: int, angle: str = "") -> str:
    ch = load_config()["channel"]
    return f"""{channel_bible()}

TASK: Write the complete narration script AND storyboard for a documentary video.
TOPIC: {topic}
CATEGORY: {category}
{('ANGLE: ' + angle) if angle else ''}

RESEARCH BRIEF (use it; do not invent facts beyond it unless you are certain):
<research>
{research}
</research>

LENGTH: about {target_words} words of narration in total (this becomes 11-14 minutes). This is a hard requirement:
the video must be over 10 minutes. Count carefully.

STRUCTURE (built for retention)
- Chapter 1 "hook" (0:00-0:45): open with the single most striking fact, image or question. Within 30 seconds
  promise the payoff the viewer gets by watching to the end. No greeting, no channel intro.
- 5-8 chapters total. Each chapter has a clear question it answers, escalates the stakes or the weirdness,
  and ends with a mini cliffhanger or open loop that pulls into the next chapter.
- A pattern interrupt every 45-90 seconds: a mascot aside, a stat, a comparison, a timeline, a change of pace.
- Callbacks to the opening hook; pay off every promise.
- Final chapter: satisfying conclusion + a big-picture "why this matters" thought, then a short outro (2-3 sentences):
  ask viewers a specific question to answer in the comments and invite them to follow {ch['mascot_name']} on more
  deep dives - natural, not begging. The last scene must be {{"type":"mascot", ...}} with "mascot":"happy".

SCENES
- Split narration into scenes of 15-45 words (5-18 seconds) - one visual idea each.
- Narration is spoken by a text-to-speech voice: write it exactly as it should be SPOKEN.
  Write numbers and years in words where pronunciation matters ("fourteen fifty-three", "about three hundred thousand"),
  no abbreviations, no symbols, no parentheses, no stage directions, no emojis.
- Visual variety: illustration and archive scenes carry most of the video, but use at least 4 graphic scenes
  (stat/timeline/list/comparison/quote) and 4-7 mascot scenes or mascot reactions. Never more than 3 of the same
  visual type in a row. Use "archive" whenever a real famous person, artwork, map, artifact, NASA photo or real
  animal photo would be more powerful than an illustration.
- Image prompts must keep a consistent cast and setting across the video (describe recurring characters the same way).

{SCENE_TYPES_DOC}

Return ONLY JSON in a ```json block, exactly this shape:
{{
  "title": "working title",
  "category": "{category}",
  "chapters": [
    {{"title": "Chapter title (2-5 words)",
      "scenes": [
        {{"narration": "...", "visual": {{...}}, "mascot": "none", "on_screen_text": ""}}
      ]}}
  ]
}}
"""


def expand_prompt(script: dict, words: int, target: int) -> str:
    return f"""This documentary script has only {words} narration words but needs about {target}
(the video must be over 10 minutes). Expand it: deepen the existing chapters with more concrete, accurate detail,
an extra story beat or two, and more vivid explanation. Keep the same JSON structure, rules and style.
Keep the opening hook and the ending. Return the COMPLETE updated JSON only, in a ```json block.

{json.dumps(script, ensure_ascii=False)}
"""


def metadata_prompt(script: dict, research: str) -> str:
    ch = load_config()["channel"]
    narration = "\n".join(
        f"[{c['title']}] " + " ".join(s["narration"] for s in c["scenes"]) for c in script["chapters"]
    )
    return f"""{channel_bible()}

TASK: Package this finished video for YouTube to maximise click-through rate and search, honestly
(the video must deliver on the title and thumbnail).

SCRIPT:
{narration}

SOURCES FROM RESEARCH (reuse the URLs):
{research[-4000:]}

Return ONLY JSON in a ```json block:
{{
 "titles": ["5 options, max 60 chars, curiosity-driven but truthful, no ALL CAPS sentences"],
 "best_title": "your pick",
 "description_hook": "2 lines shown above the fold in search - must make people click, include the main keyword",
 "description_body": "2 short paragraphs summarising what the viewer will learn (no spoilers of the big payoff)",
 "sources": ["url", "..."],
 "hashtags": ["#three", "#relevant", "#hashtags"],
 "tags": ["15-25 search tags, most specific first"],
 "thumbnails": [
   {{"text": "2-4 WORDS that complement (not repeat) the title", "highlight": "the one word to color yellow",
     "prompt": "illustration prompt for the background: one striking subject, high contrast, dramatic, simple",
     "archive_query": "optional Wikimedia Commons search if a real image would be stronger, else empty",
     "mascot": "surprised|excited|worried|thinking|pointing", "layout": "left|right|center"}}
 ],
 "pinned_comment": "a question from {ch['mascot_name']} to spark replies",
 "shorts_ideas": ["3 ideas for 45-second Shorts cut from this video, to promote it"]
}}
Give exactly 3 thumbnail concepts with clearly different ideas.
"""
