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


RETENTION_RULES = """RETENTION PLAYBOOK (this is what keeps people watching - follow it strictly)
THE HOOK (first 30 seconds decides everything; YouTube measures "still watching at 0:30")
- 0-5s PATTERN INTERRUPT: the very first line is the single most jaw-dropping, concrete, visual claim or moment of
  the whole story - start in the middle of the action. Max 12 words. No question like "have you ever wondered",
  no greeting, no channel name, no context, no definitions. Example energy:
  "This animal punches so fast, the water around its fist boils." / "In 1518, hundreds of people danced until they died."
- 5-15s CONFIRM THE CLICK: immediately deliver what the title/thumbnail promised and raise the stakes with a contrast,
  a contradiction or a "but" ("...and that's not even the strangest thing about it").
- 15-30s COMMITMENT: a specific payoff promise + an OPEN LOOP that is only paid off near the end
  ("by the end of this video you'll see why the US Navy studies its eyes" / "one of these facts is a lie - keep count").
- The hook is fast: 6-12 shots in the first 30 seconds (1-3 seconds each).

KEEPING THEM (the rest of the video)
- Story over list: a clear question drives every chapter; each answer opens a bigger question.
- Plant 2-3 open loops early and pay them off late. Re-hook every ~2 minutes ("but here's where it gets weird...").
- Every chapter ends on a tease that pulls into the next one - chapter breaks must never feel like an ending.
- Pattern interrupt every 60-90 seconds: Zib reacting, a stat slam, a comparison, a sudden question, a tone change.
- Specific beats vague: numbers, names, places, sensory details, relatable comparisons.
- Never signal the end early ("in conclusion", "to sum up", "finally"). Keep the biggest reveal for the last chapter.
  The outro call to action is max 2 short sentences.

SHOW, DON'T JUST TELL (visual pacing)
- The picture changes every 2-5 seconds. Every shot literally SHOWS what its words say at that moment:
  if the narration says "a club as fast as a bullet", the shot shows the club AND a bullet, or slams "BULLET SPEED" on screen.
- Alternate shot types for rhythm: wide illustration -> closeup on a detail -> kinetic text slam -> archive photo -> stat ...
- Use "fx":"shake" or "flash" on impact moments (explosions, punches, shocking numbers), "punch" for emphasis. Don't overuse (max ~1 in 6 shots).
"""

SCENE_TYPES_DOC = """SHOT VISUAL TYPES (each shot has exactly one "visual"):
- {"type":"broll","query":"mantis shrimp coral reef","prefer":"video|photo|any","prompt":"...","camera":"zoom_in|pan_left|..."}
    THE DEFAULT. Real stock footage or a real photo (Pexels, Pixabay, Openverse, Wikimedia, NASA), picked by a picture editor.
    Use it for everything that exists in reality: animals, places, nature, space, objects, machines, people doing
    generic things, cities, weather, lab work... "query" = 2-4 concrete, literal, visual words that a stock site would
    have ("mantis shrimp", "coral reef underwater", "bullet slow motion", "scientist microscope", "night sky stars").
    No abstract ideas, no names of specific people, no years. "prefer":"video" for anything moving (default "any").
    "prompt" = an illustration description used only if no good footage exists.
- {"type":"illustration","prompt":"...","query":"...","camera":"zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down"}
    An AI-painted image. ONLY for things no camera could ever capture: hypothetical scenarios, the far future,
    prehistoric scenes, historical events with no surviving pictures, impossible viewpoints. Max ~10% of shots.
    "prompt" = concrete visual description: subject, action, setting, composition, lighting, 15-40 words; never text;
    no real living people. Describe recurring characters/places identically every time. "query" = stock fallback words.
- {"type":"closeup","focus":"center|left|right|top|bottom","camera":"zoom_in|pan_left|..."}
    FREE extra cut: a tight, moving closeup on the PREVIOUS image (detail shot). Use it to add cuts without a new image.
- {"type":"kinetic","text":"BULLET SPEED"}  Big animated words slam onto the screen (max 5 words). Great for punchlines,
    shocking numbers and key terms. Also free.
- {"type":"split","left":{"query":"human fist","prompt":"...","label":"Human"},"right":{"query":"mantis shrimp","prompt":"...","label":"Mantis shrimp"}}
    Two real photos side by side for versus / before-after / then-now ("query" = stock search words, "prompt" = fallback).
- {"type":"archive","query":"...","caption":"...","prompt":"..."}  A REAL public-domain/CC image from Wikimedia Commons:
    famous portraits, paintings, maps, artifacts, NASA photos, real animal photos. "query" = precise Commons search terms
    ("Mehmed II portrait Bellini", "Hubble Pillars of Creation", "Odontodactylus scyllarus"). "caption" = museum label.
    "prompt" = illustration fallback if nothing is found.
- {"type":"title","text":"...","subtitle":""}  Chapter title card (only as the FIRST shot of chapters 2+; its "say" can be "").
- {"type":"stat","value":12345,"prefix":"","suffix":" km","label":"...","decimals":0}  Big animated counter.
- {"type":"timeline","events":[{"year":"1453","label":"max 5 words"}]}  3-6 events.
- {"type":"list","heading":"...","items":["max 6 words"]}  2-5 items.
- {"type":"comparison","heading":"...","items":[{"label":"...","value":123,"unit":"m"}]}  2-5 bars.
- {"type":"quote","text":"...","author":"..."}  Real, verified quotes only.
- {"type":"mascot","line":"..."}  Zib on screen reacting with a speech bubble (max 10 words): jokes, "wait, WHAT?", questions.

Per shot (optional): "fx":"none|shake|flash|punch", "label": a short on-screen tag (max 5 words: a name, place, date).
Per scene (optional): "mascot": "none|happy|surprised|thinking|excited|worried|pointing" -> Zib reacts in the corner during the scene.
Graphic shots may set "theme": "space|history|animals|hypotheticals|brand".
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
7. HOOK MATERIAL: the 5 most jaw-dropping, concrete, visual facts in the whole story, ranked. These will open the video.
8. OPEN LOOPS: 3 intriguing questions/mysteries that can be teased early and paid off late.
9. 5-10 reputable sources (URLs) used.

Write the brief in Markdown. Be thorough but dense - no padding.
"""


def script_prompt(topic: str, category: str, research: str, target_words: int, angle: str = "") -> str:
    ch = load_config()["channel"]
    return f"""{channel_bible()}

TASK: Write the complete narration AND shot-by-shot storyboard for a documentary video.
TOPIC: {topic}
CATEGORY: {category}
{('ANGLE: ' + angle) if angle else ''}

RESEARCH BRIEF (use it; do not invent facts beyond it unless you are certain):
<research>
{research}
</research>

LENGTH: about {target_words} words of narration in total (11-14 minutes). Hard requirement: over 10 minutes. Count carefully.

{RETENTION_RULES}
STRUCTURE
- Chapter 1 is the hook (0:00-0:40), built exactly as the playbook says. Then 5-8 chapters total.
- Final chapter: the biggest reveal/payoff of the open loops, a "why this matters" thought, then max 2 short sentences:
  a specific question for the comments + an invitation to follow {ch['mascot_name']} on the next deep dive.
  The very last shot must be {{"type":"mascot", ...}} and the scene's "mascot" must be "happy".

SCENES AND SHOTS
- A scene is one paragraph (20-60 words). It is split into SHOTS: each shot is the exact words spoken during it ("say")
  plus the visual on screen while they are spoken. Shots are 4-14 words (1.5-5 seconds); in the hook 3-8 words.
  Joined together, the "say" texts of a scene form its narration - split at natural phrase boundaries.
- Visual sourcing: real footage first. Roughly 55-65% of shots should be broll (real video/photos) or archive,
  at most ~10% AI illustrations, the rest closeups, kinetic text, graphics and Zib. A new broll/archive shot roughly
  every 4-8 seconds. About 2-4 shots per scene on average.
- Narration is spoken by a text-to-speech voice: write it exactly as SPOKEN. Numbers and years in words where
  pronunciation matters ("fourteen fifty-three"), no abbreviations, symbols, parentheses, stage directions or emojis.
  (Graphics like stat/timeline/kinetic may use digits.)
- Use at least 6 graphic shots (stat/timeline/list/comparison/quote) and 5-8 Zib moments (mascot shots or corner reactions).

{SCENE_TYPES_DOC}

Return ONLY JSON in a ```json block, exactly this shape:
{{
  "title": "working title",
  "category": "{category}",
  "chapters": [
    {{"title": "Chapter title (2-5 words)",
      "scenes": [
        {{"mascot": "none",
          "shots": [
            {{"say": "...", "visual": {{...}}, "fx": "none", "label": ""}}
          ]}}
      ]}}
  ]
}}
"""


def hook_doctor_prompt(script: dict, research: str) -> str:
    first = script["chapters"][0]
    rest = " ".join(sc["narration"] for c in script["chapters"][1:3] for sc in c["scenes"])[:2500]
    return f"""{channel_bible()}

You are a YouTube retention editor. The first 30 seconds decide whether a viewer stays. Rewrite this video's opening
chapter so it hooks harder.

{RETENTION_RULES}

Process (do this silently): write 4 different opening lines using different hook types (shocking fact, in-media-res
moment, contradiction/myth-bust, high-stakes question). Score each 1-10 for: concrete & visual, surprise, speed,
curiosity gap, honesty. Build the new chapter on the winner. Check: is the first line under 12 words and jaw-dropping?
Is the title's promise confirmed by 15s? Is there a specific payoff promise + open loop by 30s? Is anything slow,
vague or throat-clearing? Cut it.

TITLE: {script.get('title', '')}
RESEARCH (hook material is near the end):
{research[-5000:]}

CURRENT OPENING CHAPTER (JSON):
{json.dumps(first, ensure_ascii=False)}

WHAT COMES NEXT (do not repeat it, set it up):
{rest}

Keep roughly the same length (or shorter), keep it accurate, keep the same JSON shape (scenes -> shots, each shot
"say" + "visual"; 3-8 words per shot; a new visual every 1-3 seconds; use kinetic/closeup/fx for speed).
{SCENE_TYPES_DOC}
Return ONLY the rewritten chapter JSON object ({{"title": ..., "scenes": [...]}}) in a ```json block.
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
     "query": "2-4 word stock photo search for a striking background image (e.g. 'mantis shrimp closeup')",
     "prompt": "illustration prompt for the background if no photo fits: one striking subject, high contrast, dramatic, simple",
     "archive_query": "optional Wikimedia Commons search if a real image would be stronger, else empty",
     "mascot": "surprised|excited|worried|thinking|pointing", "layout": "left|right|center"}}
 ],
 "pinned_comment": "a question from {ch['mascot_name']} to spark replies",
 "shorts_ideas": ["3 ideas for 45-second Shorts cut from this video, to promote it"]
}}
Give exactly 3 thumbnail concepts with clearly different ideas.
"""
