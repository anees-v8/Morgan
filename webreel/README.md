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
