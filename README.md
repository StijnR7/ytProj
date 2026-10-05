# Probe Into It Studio

A local app that turns a topic into a finished, upload-ready **10-14 minute animated documentary** for YouTube.
It handles the research, script, storyboard, narration, illustrations, animation, music, thumbnails, title,
description, chapters, tags and captions, all narrated by **Zib**, the channel's tiny probe mascot.

**Cost: nothing beyond your Claude subscription.** Every part runs on your own PC or uses free sources:

| Job | Tool | Cost |
|---|---|---|
| Ideas, research (with web search), script, storyboard, titles, description, tags | Claude Code CLI (`claude -p`) on your **subscription login** | included |
| Narration voice | [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), open-source TTS, runs on CPU | free |
| Illustrations | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) **Vulkan** build + SDXL + Lightning LoRA, on your RX 6700 XT | free |
| Real images (kings, paintings, NASA photos, animals) | Wikimedia Commons (public domain / CC, credits auto-added) | free |
| Animation, motion graphics, mascot, thumbnails | Built-in Python renderer (Pillow + FFmpeg) | free |
| Music | Your tracks from the YouTube Audio Library, or Zib's built-in ambient composer | free |

> The app strips `ANTHROPIC_API_KEY` from Claude's environment, so it never bills the pay-per-token API by accident.

---

## 1. Install (Windows, one time)

1. **Python 3.12**: https://www.python.org/downloads/ (tick **"Add python.exe to PATH"**).
2. **Claude Code**: open PowerShell and run `irm https://claude.ai/install.ps1 | iex`, then run `claude` once and
   log in with your Claude account (Pro/Max).
3. **AMD driver**: make sure your Radeon driver is up to date (Vulkan support is built in).
4. Double-click **`setup.bat`**. It creates a virtual environment, installs packages, downloads the voice model and
   (if you say yes) stable-diffusion.cpp + SDXL (~7.5 GB). Then it creates the channel art and runs a self-check.
5. Double-click **`start.bat`**. The studio opens in your browser at http://127.0.0.1:7860

Check the GPU image setup at any time with:
```
.venv\Scripts\activate
python -m ytfactory check --test-image
```

## 2. Make a video

1. **Brainstorm ideas** (left sidebar) → Claude fills a backlog of titles across history, space, animals and hypotheticals.
   Or type your own topic.
2. Click **① Write + storyboard**. This runs research → script → metadata → voice → images → storyboard previews.
3. **Review.** Read the storyboard (a preview frame for every scene), fix anything in the **script** tab
   (narration, visuals, Zib's reactions), re-roll images you don't like (🎲) or give a scene a new prompt.
4. Click **② Render video + package**. This renders the MP4, the three thumbnails, and the upload files.
5. **Publish** tab: watch the video, copy the title, description, tags and pinned comment, and download
   `captions.srt`. Follow `output/UPLOAD_CHECKLIST.md`.

Everything for a video lives in `projects/<name>/`; the finished files are in `projects/<name>/output/`.

### Command line (same features)
```
python -m ytfactory ideas --generate        # brainstorm
python -m ytfactory new --idea 3            # or: new "Why octopuses are basically aliens" --category animals
python -m ytfactory run <slug> --to storyboard
python -m ytfactory run <slug> --from render
python -m ytfactory run <slug> --from voice --force   # redo from a stage
python -m ytfactory voices                  # audition narrator voices -> voice_samples/
python -m ytfactory branding                # regenerate channel art
```

## 3. What each video contains

- **Script**: about 2,000 words written to a retention playbook (`RETENTION_RULES` in `ytfactory/prompts.py`):
  - **The hook (first 30 s)**: 0-5 s opens with the single most striking, concrete claim (no greeting, no context);
    5-15 s delivers what the title promised and raises the stakes; 15-30 s promises a specific payoff and opens a loop
    that only closes near the end.
  - A **hook doctor** pass then has Claude write four alternative openings, score them, and rebuild the first chapter
    around the best one.
  - After the hook: two or three open loops paid off late, a re-hook roughly every 2 minutes, a pattern interrupt every
    60-90 s, chapters that end on a tease, no dead air, and no "in conclusion".
  - If the script comes out too short, Claude is asked to expand it automatically, so videos land over 10 minutes.
- **Shot-by-shot storyboard**: every paragraph is cut into **shots of 1.5-5 s**, and each shot shows what is being said
  at that moment. Shot types:
  - AI illustration (strong pan/zoom with floating particles)
  - **closeup** (a free extra cut on a detail of the previous image)
  - **kinetic text** (big words slam onto the screen)
  - **split-screen VS**
  - real archive photo, stat counter, timeline, list, bar comparison, quote, chapter title card
  - Zib with a speech bubble

  Every cut has a small zoom-settle, impact moments get shake, flash or punch effects, and paragraphs are joined by hard
  cuts, whip-pans, or a brand wipe on chapter titles. Zib reacts in the corner, and its mouth moves with the voice.
- **Audio**: narration, ducked background music, whooshes, pops and impacts timed to the cuts, loudness-normalised to
  YouTube's -14 LUFS.
- **Video**: 1920×1080, 30 fps, H.264, and a 20 s end screen with slots for YouTube's end-screen elements.
- **Upload package**: 3 thumbnail variants (for *Test & compare*), title plus 4 alternatives, description with
  auto-timestamped **chapters**, sources and image credits, tags, `captions.srt`, pinned comment, and Shorts ideas.

## 4. Settings (`config.yaml`)

- `voice.kokoro_voice`: Zib's voice (`am_michael` by default; run `python -m ytfactory voices` to hear the options).
- `images.backend`: `sdcpp` (default), `comfyui` (if you prefer ComfyUI; set the checkpoint name), or `none`
  (no AI images: built-in animated art and Wikimedia images only; renders right away).
- `images.style`: the style prompt added to every illustration, which keeps the look consistent.
- `claude.model`: leave empty for the default, or `opus` / `sonnet`.
- `video.workers`: rendering processes (auto = half your CPU threads).
- `video.burn_captions`: burn subtitles into the video (they're always exported as `.srt`).
- Music: drop `.mp3` files from the YouTube Audio Library (free, no attribution needed for most) into `assets/music/`.

### Image generation notes for the RX 6700 XT
- stable-diffusion.cpp's Vulkan build needs no ROCm/ZLUDA; it works on Windows with the normal AMD driver.
- The default is SDXL base + the 8-step **SDXL-Lightning** LoRA (fast; expect roughly 10-30 s per image on 12 GB).
  The new shot-based edit uses about 80-150 new images per video (capped by `images.max_images`; extra shots reuse
  earlier images as closeups), so expect roughly 30-60 minutes of image generation. Lower `max_images` for speed.
- If you see black or broken images, change `cfg`, `steps` or `sampler` in `config.yaml`, or swap the model for any
  SDXL checkpoint you like (put the `.safetensors` in `models/` and set `images.sdcpp.model`; set `lora: ""` for
  non-base checkpoints). Run `python -m ytfactory check --test-image` to try settings quickly.
- Prefer ComfyUI? Install ComfyUI (DirectML or ZLUDA build for AMD), start it, and set `images.backend: comfyui`.

## 5. Honest advice for the channel

- **Watch every video before publishing and fact-check** the points the research brief marks `[DISPUTED]` or
  `[UNVERIFIED]`. Claude is good but not infallible, and educational channels live on trust.
- **YouTube's monetisation rules** (the "inauthentic / mass-produced content" policy) penalise channels
  that pump out near-identical, low-effort AI videos. What keeps you safe is what also makes the videos good:
  original angles, real research, your own edits to the script, varied formats, and a consistent personality (Zib).
  Quality over volume: one strong video a week beats one a day.
- Animated videos narrated by a cartoon robot normally don't need YouTube's "altered or synthetic content"
  label. Tick it if you ever show realistic AI images of real people or real events.
- Don't be shy about editing: the script tab is the fastest way to make each video yours.

## Project layout
```
config.yaml            all settings
setup.bat / start.bat  Windows install + launch
channel/               channel kit: CHANNEL.md, profile picture, banner, watermark, mascot sheet
assets/fonts           bundled open-licence fonts
assets/music           your music tracks (optional)
ytfactory/             the app
  prompts.py           channel voice + all Claude prompts (tweak the style here)
  pipeline.py          the stages
  render/              scenes, mascot, backgrounds, audio, engine
  web/                 dashboard
projects/<slug>/       one folder per video (research.md, script.json, audio/, images/, storyboard/, output/)
```
