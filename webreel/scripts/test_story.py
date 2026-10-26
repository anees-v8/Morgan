"""
Plan-only preview: scout a website and print the film plan the Story Director writes for it
(narration, cards, what gets clicked). No video is rendered, so it takes ~30-60 seconds and is the
fastest way to judge/tune the Gemini prompt in engine/ai/story_director.py.

    python webreel/scripts/test_story.py --url https://stripe.com
    python webreel/scripts/test_story.py --url https://linear.app --no-llm     # page-text plan only

Needs GEMINI_API_KEY (env var or webreel/.env) for the Gemini plan; without it the plan is built
from the page text alone.
"""
import sys
import json
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

from webreel.engine.ai.gemini_client import GeminiClient
from webreel.engine.ai.site_brief import build_site_brief
from webreel.engine.ai.story_director import StoryDirector, build_evidence
from webreel.engine.browser.stealth import STEALTH_SCRIPTS, get_stealth_headers
from webreel.engine.config import config


async def main():
    ap = argparse.ArgumentParser(description="Preview the dynamic film plan for a website")
    ap.add_argument("--url", default="https://stripe.com")
    ap.add_argument("--no-llm", action="store_true", help="skip Gemini; build the plan from page text only")
    ap.add_argument("--save", default="", help="write the full plan JSON to this path")
    args = ap.parse_args()
    url = args.url if args.url.startswith("http") else "https://" + args.url

    client = GeminiClient(api_key="" if args.no_llm else None)
    print(f"\nURL: {url}")
    print(f"Gemini: {'ON (' + config.gemini_models.split(',')[0] + ' ...)' if client.enabled else 'OFF (no key) - page-text plan'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--hide-scrollbars"])
        ctx = await browser.new_context(viewport={"width": config.capture_width, "height": config.capture_height},
                                        user_agent=config.user_agent, extra_http_headers=get_stealth_headers())
        await ctx.add_init_script(STEALTH_SCRIPTS)
        brief = await build_site_brief(ctx, url)
        await browser.close()

    ev = json.dumps(build_evidence(brief), ensure_ascii=False)
    print(f"Scouted: {len(brief['headings'])} headings, {len(brief['actions'])} controls "
          f"({sum(a['can_click'] for a in brief['actions'])} safe to click), {len(brief['numbers'])} numbers, "
          f"{len(brief['pages'])} sub-pages, {len(brief['screenshots'])} screenshots; evidence {len(ev)} chars; "
          f"brand colour {brief['brand_rgb']}")

    plan = await StoryDirector(client).plan(brief)
    print(f"\nPLAN SOURCE: {plan['source']}   BRAND: {plan['brand_name']}   TAGLINE: {plan['tagline']}")
    if plan.get("audience"):
        print(f"AUDIENCE: {plan['audience']}")
    print("\nCARDS")
    for c in plan["cards"]:
        print(f"  [{c['category']}] {c['title']} - {c['desc']}")
    total = 0
    print("\nSCENES")
    for i, s in enumerate(plan["scenes"], 1):
        w = len(s["say"].split())
        total += w
        press = ""
        if s["target_label"]:
            press = f" -> {'CLICK' if s['can_click'] else 'press (not sent)'} '{s['target_label']}'"
        print(f"\n  {i}. [{s['scene_type']}] {s['title']}   (~{w / 2.4:.0f}s, {w} words, card {s['card'] + 1})")
        print(f"     scroll: {s['scroll_to'] or '-'}   pointer on: {s['focus_text'] or '-'}{press}")
        print(f"     \"{s['say']}\"")
    print(f"\n  OUTRO: \"{plan['outro_say']}\"")
    print(f"\nNarration total: {total} words (~{total / 2.4:.0f}s) + outro")
    if plan.get("report"):
        print("\nVALIDATOR FIXED / REMOVED:")
        for r in plan["report"]:
            print("  -", r)
    if plan.get("llm_errors"):
        print("\nGEMINI NOTES:")
        for e in plan["llm_errors"]:
            print("  -", e)
    if args.save:
        Path(args.save).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nsaved -> {args.save}")


if __name__ == "__main__":
    asyncio.run(main())
