# 🎬 WebReel — Autonomous AI Website Video Generator

> **Turn any live website URL into a professional, narrated 90-second marketing video in 4 minutes — fully autonomously.**

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Run the Autonomous Pipeline via CLI
```bash
python webreel/scripts/test_pipeline.py --url https://stripe.com
```

### 3. Launch the Full Web Studio + API Server
```bash
python -m uvicorn webreel.api.main:app --reload --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🏗️ Architecture & Philosophy

- **Zero API Costs:** Built to run on Google Cloud Run + Vercel + Cloudflare R2 on Rs.0 cloud budget.
- **Real Browser Navigation:** Uses Chromium via Playwright to discover pages, interact with CTAs, and record authentic high-DPI viewports.
- **Multimodal Intelligence:** Gemini 2.0 Flash vision extracts USP, headlines, and value propositions.
- **Cinematic Production:** FFmpeg compositor with Ken Burns 0-6% motion, lower-third overlays, cursor click ripples, and automatic background music ducking (voice 100%, music 8%).
- **Interactive Mindmap:** View the complete strategic and technical blueprint at `webreel_mindmap.html`.

### Live-capture showcase renderer

Each scene is recorded as the **real page in motion** (CDP screencast, ~60fps, exact timestamps) while a human-like pointer
choreography drives the real mouse, so hover states, route transitions and page animations are genuine. The renderer then
frames it with a spring-physics camera, motion blur, a softly tilted 3D window and three synced benefit cards.
A static-screenshot path is kept as an automatic fallback.

| Env var | Default | Meaning |
|---|---|---|
| `WEBREEL_LIVE_CAPTURE` | `1` | `0` = screenshots only (no live clips) |
| `WEBREEL_CAPTURE_W` / `WEBREEL_CAPTURE_H` | `1280` / `800` | Capture viewport (16:10, matches the showcase window) |
| `VIDEO_FPS` | `60` | Output frame rate (use `30` for faster renders) |
| `WEBREEL_RENDER_WORKERS` | `min(3, cpus-1)` | Scenes rendered in parallel |
| `WEBREEL_KEEP_LIVE_FRAMES` | `0` | Keep the per-scene JPEG frame dumps for debugging |
| `WEBREEL_DYNAMIC_STORY` | `1` | `0` = legacy fixed journey / templates |
| `GEMINI_API_KEY` | - | Free-tier key; enables the Gemini story director (set it in `webreel/.env`) |
| `GEMINI_MODELS` | see `.env.example` | Model fallback chain |
| `WEBREEL_NARRATION_LANGUAGE` | `English` | Language of the script |
| `WEBREEL_SCENES` | `4` | Number of story scenes (3-5) |

**Dynamic story:** the site is scouted first (headings, buttons, prices, brand colour, screenshots for OCR). A Gemini
"director" writes the narration, the 3 benefit cards and the click path from the site's *own* content; every label must exist
on the page and every number must appear in the page text (validator). Without a key the same flow runs from page text only.
Preview a plan without rendering: `python webreel/scripts/test_story.py --url https://example.com`.
