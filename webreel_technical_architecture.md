# 🏗️ WebReel — Zero Budget Technical Architecture
### Complete Stack, Folder Structure, Hosting & Video Quality Guide

---

> **Budget Reality:** Rs.1,000 for domain. Everything else = Rs.0.

---

## 1. 💡 Core Philosophy: Free Until You're Paid

    Phase 0 (Now):     100% free — Free tiers + open-source only
    Phase 1 (Launch):  Still free tiers, apply for cloud credits
    Phase 2 (Credits): 200K+ dollars in cloud credits from Google/AWS/Azure
    Phase 3 (Revenue): Pay with customer money, not your own

**Rule:** Never pay for anything until a customer pays you first.

---

## 2. 🗂️ Project Folder Structure

    webreel/
    │
    ├── engine/                    # Core AI pipeline (Python)
    │   ├── browser/
    │   │   ├── agent.py           # LLM-directed browser agent (browser-use)
    │   │   ├── crawler.py         # Page discovery and link graph
    │   │   ├── stealth.py         # Anti-bot evasion layer
    │   │   └── recorder.py        # Playwright video + screenshot capture
    │   │
    │   ├── ai/                    # AI intelligence layer
    │   │   ├── director.py        # LLM decides which pages to visit
    │   │   ├── analyzer.py        # Vision model analyzes screenshots
    │   │   ├── scriptwriter.py    # Generates narrator script
    │   │   └── summarizer.py      # Extracts: name, tagline, features, USP
    │   │
    │   ├── audio/
    │   │   ├── tts.py             # Kokoro TTS (free, local) voiceover
    │   │   ├── mixer.py           # Mix voiceover + background music
    │   │   └── music/
    │   │       ├── corporate_soft.mp3
    │   │       ├── tech_upbeat.mp3
    │   │       └── minimal_ambient.mp3
    │   │
    │   ├── video/
    │   │   ├── producer.py        # Main orchestrator
    │   │   ├── effects.py         # Ken Burns, zoom-to-element, crossfade
    │   │   ├── overlay.py         # Lower thirds, titles, captions, cursor
    │   │   ├── transitions.py     # FFmpeg xfade transition library
    │   │   └── exporter.py        # Final H.264 export via FFmpeg
    │   │
    │   ├── assets/
    │   │   ├── fonts/             # Inter, Outfit (Google Fonts)
    │   │   ├── overlays/          # Lower-third templates (PNG alpha)
    │   │   ├── cursor.png         # Animated cursor sprite
    │   │   ├── watermark.png      # "Made with WebReel" watermark
    │   │   └── outro_bg.png       # Branded outro background
    │   │
    │   ├── pipeline.py            # Master pipeline: URL -> video
    │   └── config.py              # All settings: resolution, fps, durations
    │
    ├── api/                       # Backend REST API (Python FastAPI)
    │   ├── main.py
    │   ├── routes/
    │   │   ├── generate.py        # POST /generate
    │   │   ├── status.py          # GET /status/{job_id}
    │   │   └── download.py        # GET /download/{job_id}
    │   ├── models/
    │   │   ├── job.py
    │   │   └── video.py
    │   ├── services/
    │   │   ├── queue.py
    │   │   ├── storage.py         # Upload to Cloudflare R2
    │   │   └── db.py              # Supabase client
    │   ├── Dockerfile
    │   └── requirements.txt
    │
    ├── worker/                    # Background job worker
    │   ├── worker.py              # Runs the full AI video pipeline
    │   ├── Dockerfile             # Heavy container: Playwright + FFmpeg
    │   └── requirements.txt
    │
    ├── web/                       # Frontend (Next.js 14 App Router)
    │   ├── app/
    │   │   ├── page.tsx           # Landing page
    │   │   ├── generate/page.tsx  # URL input + progress UI
    │   │   ├── result/[jobId]/page.tsx  # Video player + download
    │   │   └── layout.tsx
    │   ├── components/
    │   │   ├── HeroSection.tsx
    │   │   ├── UrlInput.tsx
    │   │   ├── ProgressTracker.tsx
    │   │   ├── VideoPlayer.tsx
    │   │   └── PricingCard.tsx
    │   └── package.json
    │
    ├── scripts/
    │   ├── test_pipeline.py       # Run pipeline locally end-to-end
    │   ├── download_fonts.py
    │   └── seed_music.py
    │
    ├── .env.example
    ├── .gitignore
    ├── docker-compose.yml         # Local dev (all services)
    └── README.md

---

## 3. 🤖 AI Stack — 100% Free

### LLM and Vision: Google Gemini (FREE)

| Model | Use Case | Free Limit |
|---|---|---|
| Gemini 2.0 Flash | Director agent, page analysis, script | 15 RPM, 1,500 RPD |
| Gemini 1.5 Flash | Fallback for high-volume jobs | 15 RPM, 1,500 RPD |

3 prompts power the entire pipeline:

    PROMPT 1: Director
    "You are a product demo video director. Given this homepage screenshot of {domain},
    identify the 5 most impressive pages for a 90-second product video.
    Prioritize: Features, Pricing, live demos, About.
    Avoid: Login, Signup, Docs, Legal.
    Return JSON: [{"url": "...", "reason": "...", "duration_seconds": 12}]"

    PROMPT 2: Analyzer (per page screenshot)
    "Analyze this screenshot of {page_url}. Return JSON:
    { page_purpose, key_elements[], zoom_target, narration_text, visual_highlight }"

    PROMPT 3: Scriptwriter (final narration)
    "Write a 90-second professional narrator script for {website_name}.
    Tone: Confident, clear — like Apple product launch narration.
    Structure: Intro(5s) > Homepage(10s) > Features(30s) > Pricing(10s) > Outro(5s)
    Return JSON with scene breakdowns and narrator text per scene."

### Voiceover: Kokoro TTS (FREE, Apache 2.0)

Rivals ElevenLabs quality. Runs locally on CPU. Zero API cost. Commercial use allowed.

    pip install kokoro soundfile
    
    Voice map:
      saas/startup:  am_adam    (deep, authoritative male)
      ecommerce:     af_heart   (warm, friendly female)
      portfolio:     af_sarah   (professional, clear female)
      default:       af_heart
    
    Settings:
      speed: 1.08   (slightly brisk = confident, energetic)
      silence_between_sections: 0.35s

### Browser Automation: Playwright + browser-use (FREE, MIT)

    pip install playwright browser-use
    playwright install chromium

### Video Production: FFmpeg + MoviePy + Pillow + OpenCV (ALL FREE)

    FFmpeg    Video encoding, Ken Burns, xfade transitions, audio sync
    MoviePy   Python wrapper (MIT license)
    Pillow    Lower-thirds, watermark, cursor overlays
    OpenCV    Zoom-to-element, frame manipulation

---

## 4. 🌐 Hosting Architecture — Rs.0 Cost

    [USER BROWSER]
         |
         | HTTPS
         v
    [VERCEL - Frontend FREE Hobby Plan]
     Next.js 14 | webreel.vercel.app | 100GB bandwidth/month free
         |
         | REST API calls
         v
    [GOOGLE CLOUD RUN - API FREE Always-Free Tier]
     FastAPI container | Scale-to-zero: Rs.0 when idle
     2M free requests/month, 180K vCPU-sec/month
         |
         | Creates job, triggers worker
         v
    [GOOGLE CLOUD RUN - Worker FREE Tier / Credits]
     Python + Playwright + Kokoro + FFmpeg
     Runs full AI video pipeline (~5-8 min per video)
         |              |
         v              v
    [SUPABASE FREE]  [CLOUDFLARE R2 FREE]
     PostgreSQL        Video storage + CDN delivery
     Auth              10GB free, ZERO egress fees
     500MB DB          Videos load fast globally

### Monthly Cost Breakdown

| Service | Provider | Free Limit | Cost |
|---|---|---|---|
| Frontend | Vercel Hobby | 100GB bandwidth | Rs.0 |
| API Backend | Google Cloud Run | 2M requests | Rs.0 |
| Video Worker | Google Cloud Run | 180K vCPU-sec | Rs.0 |
| Database | Supabase Free | 500MB, 50K rows | Rs.0 |
| Auth | Supabase Auth | 50K MAU | Rs.0 |
| Video Storage | Cloudflare R2 | 10GB, no egress | Rs.0 |
| CDN | Cloudflare Free | Unlimited | Rs.0 |
| LLM / Vision | Gemini API Free | 1,500 req/day | Rs.0 |
| TTS | Kokoro (local) | Unlimited | Rs.0 |
| Video Engine | FFmpeg/MoviePy | Unlimited | Rs.0 |
| Music | Pixabay / FMA | Commercial OK | Rs.0 |
| Domain | Namecheap .in | — | Rs.800/yr |
| TOTAL | | | Rs.800/year |

### Domain Strategy

    Rs.0 launch:   webreel.vercel.app     (good for beta + investor demos)
    Rs.700/yr:     webreel.in             (RECOMMENDED — spend your Rs.1000 here)
    After revenue: webreel.ai             (premium brand name)

---

## 5. 🎬 Video Quality Specification

> This is what raises money. Every frame must look premium.

### Output Specs

    Resolution:  1920x1080 (1080p) — MVP standard
                 3840x2160 (4K) — paid tier
    Frame Rate:  30fps
    Codec:       H.264 (libx264) — universal compat
    Audio:       AAC stereo, 192kbps
    Container:   .mp4
    Duration:    90 seconds (60-120 range)
    File Size:   15-40MB compressed
    Color Space: yuv420p (required for browser playback)

### The 90-Second Video Template

    [0:00-0:05]  BRANDED INTRO
                 Black bg fades in
                 Website favicon + domain animates (scale + fade)
                 Tagline appears below
    
    [0:05-0:20]  HOMEPAGE HERO
                 Full homepage with Ken Burns effect (slow zoom-out)
                 Lower-third: "Website Name · Category" slides in
                 Cursor glides to CTA, hovers with soft glow ring
                 Narrator: "Welcome to [name]. [What it does]."
    
    [0:20-0:55]  FEATURE WALKTHROUGH (3-4 pages, ~10s each)
                 Per page:
                   Crossfade from previous (0.8s fadeblack)
                   Ken Burns pan begins
                   Cursor moves to key element (0.5s travel)
                   Click ripple animation (expanding rings)
                   Zoom into element (1.6x smooth, 0.5s ease)
                   Hold 2s while narrator speaks
                   Zoom back out (0.4s)
                   Lower-third shows feature name
    
    [0:55-1:10]  PRICING PAGE
                 Pricing table fades in
                 Best plan gets animated glow border
                 Cursor clicks CTA
                 Narrator: "Plans from [price]. Free to start."
    
    [1:10-1:20]  BRANDED OUTRO
                 Fade to near-black
                 Domain URL types in (typewriter effect, white)
                 Tagline fades below
                 "Generated by WebReel.in" — small, bottom-right
                 Music fades out

### Effects Specs

    Ken Burns:
      FFmpeg zoompan: 0% to 8% zoom over clip duration
      Feels cinematic, not slideshowy
    
    Crossfade:
      FFmpeg xfade=transition=fadeblack:duration=0.8
    
    Zoom to element:
      Animate from full frame to 1.6x crop centered on element
      0.5s ease-in-out, hold 2s, ease-out back to full
    
    Cursor overlay:
      PNG sprite composited via FFmpeg overlay filter
      Animated movement via keyframe coordinates
      Click ripple: 3 expanding circles, opacity fading

### Lower-Third Design Spec

    Background:   rgba(0,0,0,0.68)
    Accent bar:   3px gradient from brand color (extracted from favicon)
    Name font:    Inter Bold, 26px, white
    Label font:   Inter Medium, 13px, rgba(255,255,255,0.7)
    Radius:       4px
    Padding:      12px 18px
    Position:     40px from left, 60px from bottom
    Animation:    slideIn 0.35s ease-out | hold 4s | fadeOut 0.2s

---

## 6. 🎵 Audio Strategy

### Script Formula (Gemini generates this)

    INTRO (5s):    "{name}. {tagline}."
    HOMEPAGE (10s): "Built for {audience}, {name} makes it simple to {value}."
    FEATURE 1 (10s): "{feature}: {what it does}. {outcome}."
    FEATURE 2 (10s): "With {feature}, {benefit}."
    FEATURE 3 (10s): "{feature} — {differentiator}."
    PRICING (10s):  "Plans from {price}. Try it free at {domain}."
    OUTRO (5s):    "{name}. {tagline}."

### Music Mixing

    Voiceover: 100% volume
    Music:     8% volume (-22dB) — atmosphere only
    
    FFmpeg mix command:
      [1:a]volume=0.08[music];
      [0:a][music]amix=inputs=2:duration=first:weights=1 0.08[out]

    Free Music Sources:
      pixabay.com/music/                    (Free, commercial OK)
      freemusicarchive.org                  (CC licenses)
      studio.youtube.com/channel/music      (YouTube Audio Library)
      bensound.com/free-music-for-videos    (Attribution OK)

---

## 7. ☁️ Cloud Credits — Apply This Week

    PRIORITY   PROGRAM                    CREDITS       TIME
    ─────────────────────────────────────────────────────────
    1          Google for Startups        ,000     1-2 weeks
               cloud.google.com/startup
    
    2          Microsoft for Startups     ,000     1 week
               foundershub.startups.microsoft.com
    
    3          AWS Activate               ,000     3-5 days
               aws.amazon.com/activate
    
    4          NVIDIA Inception           GPU access   2 weeks
               nvidia.com/startups
    ─────────────────────────────────────────────────────────
               TOTAL POSSIBLE:           ,000+

Google Application tip — write exactly this in the description:
    "WebReel is an AI agent that autonomously navigates any website in Chromium
    using Playwright and browser-use, analyzes each page using Gemini Vision,
    writes a narration script, and produces a professional cinematic video
    fully automatically. We use Gemini 2.0 Flash for all LLM/vision tasks
    and deploy on Google Cloud Run."

### India-Specific Programs

    Startup India DPIIT     3 years 0% income tax    startupindia.gov.in
    NASSCOM 10K Startups    Credits + VC network     10000startups.com
    T-Hub Hyderabad         Rs.10-25L + mentorship   t-hub.co
    iCreate Gujarat         Rs.25L grant             icreate.org.in
    Startup India Seed Fund Up to Rs.50L             startupindia.gov.in

---

## 8. 🔑 .env.example

    # Google AI
    GEMINI_API_KEY=your_gemini_api_key_here
    GOOGLE_PROJECT_ID=webreel-prod
    
    # Supabase
    SUPABASE_URL=https://xxxxx.supabase.co
    SUPABASE_ANON_KEY=your_anon_key
    SUPABASE_SERVICE_ROLE_KEY=your_service_key
    
    # Cloudflare R2
    R2_ACCOUNT_ID=your_cloudflare_account_id
    R2_ACCESS_KEY_ID=your_r2_access_key
    R2_SECRET_ACCESS_KEY=your_r2_secret
    R2_BUCKET_NAME=webreel-videos
    R2_PUBLIC_URL=https://videos.webreel.in
    
    # Video Engine
    VIDEO_RESOLUTION_W=1920
    VIDEO_RESOLUTION_H=1080
    VIDEO_FPS=30
    VIDEO_DURATION_TARGET=90
    MAX_PAGES_TO_VISIT=6
    
    # TTS
    TTS_DEFAULT_VOICE=af_heart
    TTS_SPEED=1.08
    
    # App
    APP_ENV=production
    MAX_CONCURRENT_JOBS=3
    JOB_TIMEOUT_SECONDS=600
    FREE_TIER_MAX_JOBS_PER_DAY=3

---

## 9. 🐳 Worker Dockerfile

    FROM python:3.11-slim
    
    RUN apt-get update && apt-get install -y \
        ffmpeg espeak-ng libgl1-mesa-glx libglib2.0-0 wget \
        && rm -rf /var/lib/apt/lists/*
    
    WORKDIR /app
    COPY worker/requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    RUN playwright install chromium
    RUN playwright install-deps chromium
    COPY . .
    CMD ["python", "worker/worker.py"]

    Key packages:
      playwright==1.48.0
      browser-use==0.1.40
      google-generativeai==0.8.0
      moviepy==1.0.3
      Pillow==10.4.0
      opencv-python-headless==4.10.0
      kokoro==0.9.2
      soundfile==0.12.1
      supabase==2.6.0
      boto3==1.35.0

---

## 10. 📅 28-Day Build Sprint

    WEEK 1: Core Engine
      Day 1-2:  Project setup, Playwright opens browser, takes screenshots
      Day 3-4:  Gemini API connected, analyzes screenshot to JSON
      Day 5-6:  MoviePy assembles screenshots to MP4 with Ken Burns
      Day 7:    Kokoro TTS voiceover, FFmpeg syncs audio to video
    
    WEEK 2: Intelligence and Polish
      Day 8-9:  Director agent, LLM plans which pages to visit
      Day 10-11: Cursor overlay + click ripple + zoom-to-element
      Day 12-13: Lower-thirds, background music, auto-ducking
      Day 14:   Branded intro/outro, full URL-to-video in under 10 min
    
    WEEK 3: Backend and Frontend
      Day 15-16: FastAPI: /generate + /status + /download
      Day 17:   Supabase schema: jobs + users tables
      Day 18:   Cloudflare R2 upload + CDN URL generation
      Day 19-20: Deploy API to Cloud Run, Frontend to Vercel
      Day 21:   Full flow: Web UI -> API -> Worker -> Video -> Player
    
    WEEK 4: Demo Content and Launch
      Day 22-23: Generate 5 demo videos (Stripe, Notion, Figma, Linear, Vercel)
      Day 24:   Polish landing page, add waitlist form
      Day 25:   Record the meta demo (WebReel generating a video)
      Day 26:   Tweet the demo — tag the companies whose sites you used
      Day 27:   Post Show HN on Hacker News
      Day 28:   Schedule Product Hunt for following Tuesday

---

## 11. 🎯 Investor Demo Video Rules

    MUST SHOW:
      URL being typed           proves it is real, not a template
      Browser opening live      proves it is autonomous
      AI navigating the site    this is the WOW moment
      Cursor making real clicks proves real interaction
      Final video output        must look like 5000 dollar agency work
      "Generated in 4 minutes"  end card — this is the pitch
    
    AUDIO:
      Sound like a human (Kokoro af_heart voice, speed 1.08)
      Subtle background music at 8% volume
      End with clear call to action
    
    FIRST 5 DEMO VIDEOS (these go viral):
      stripe.com    Every developer knows it, clean UI
      notion.so     Huge user base, they will share it
      linear.app    Designer community loves it
      vercel.com    Developer community
      figma.com     Design community
    
    TWEET FORMULA:
      "I gave my AI agent the URL stripe.com and told it to make
       a professional product video.
       4 minutes later, this happened."
       [attach the video]

---

## 12. 🔮 Stack Upgrade Path

    NOW (Rs.0)               CREDITS ()           REVENUE
    ─────────────────────────────────────────────────────────────
    Gemini Free 1.5K/day  -> Gemini Pay-as-you-go   -> Multi-model
    Kokoro TTS local CPU  -> Kokoro on GPU           -> ElevenLabs
    Cloud Run free tier   -> Cloud Run scaled        -> GPU VMs
    Cloudflare R2 10GB    -> R2 paid 0.015/GB        -> Streaming CDN
    Supabase free 500MB   -> Supabase Pro 25/mo      -> + Redis
    Vercel Hobby free     -> Vercel Pro 20/mo        -> Enterprise
    Manual job queue      -> Cloud Tasks             -> Celery+Redis

---

Last updated: October 2026 | WebReel Technical Architecture | Morgan Project
