"""
Story runner: performs a StoryDirector plan on the live site, scene by scene.

Nothing here knows any particular website. Every thing the pointer touches is resolved *at run time*
from the plan's exact labels against the real page: headings to scroll to, the text the narrator is
describing (pointer rests on it), and the one control a scene presses at its end. A press is a REAL
click only when the control is classified safe (same-site navigation, tabs, plain buttons - never
login/signup/checkout/forms); anything else is shown as a press without being sent.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .crawler import IGNORE_PATTERNS

logger = logging.getLogger("webreel.story")

# Resolve visible text -> element rect (viewport coordinates) on the page as it is *right now*.
FIND_JS = r"""
(args) => {
  const [text, clickable] = args;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const want = norm(text);
  if (!want) return null;
  const vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 4 && r.height > 4 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05; };
  const sel = clickable ? 'a,button,[role=button],[role=tab],[role=link]' : 'h1,h2,h3,h4,h5,h6,p,li,span,div,a,button,strong,b';
  let best = null, bestScore = 1e18;
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || e.closest('[role=dialog],[aria-modal=true]')) continue;
    if (norm(e.getAttribute('aria-label') || e.innerText) !== want) continue;
    const r = e.getBoundingClientRect();
    const off = (r.bottom < 0 || r.top > innerHeight) ? 1e7 : 0;
    // Text lookups: the tightest element that carries the text. Controls: prefer the prominent one -
    // higher on screen and bigger (hero CTA / header nav) over a small footer link with the same label.
    const score = clickable ? off + r.top - Math.min(r.width * r.height, 20000) / 50 : r.width * r.height + off;
    if (score < bestScore) { best = e; bestScore = score; }
  }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
  const topEl = (cx >= 0 && cy >= 0 && cx <= innerWidth && cy <= innerHeight) ? document.elementFromPoint(cx, cy) : null;
  return {
    x: r.x, y: r.y, width: r.width, height: r.height, tag: best.tagName,
    href: best.href || '', type: best.type || '', inForm: !!best.closest('form'),
    inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
    docY: r.top + scrollY,
    covered: !!topEl && !(best === topEl || best.contains(topEl) || topEl.contains(best)),
  };
}
"""

_NO_POPUP_TABS_JS = "() => document.querySelectorAll('a[target=\"_blank\"]').forEach(a => a.removeAttribute('target'))"
_DIALOG_JS = "() => !!document.querySelector('[role=dialog]:not([aria-hidden=true]), [aria-modal=true]')"
_DENY_PATH = re.compile("|".join(IGNORE_PATTERNS))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "scene").lower()).strip("_")[:18] or "scene"


async def _find(page, text: str, clickable: bool) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return await page.evaluate(FIND_JS, [text, clickable])
    except Exception:
        return None


async def _scroll_to_doc_y(rec, page, beat, doc_y: float) -> None:
    target = max(0.0, doc_y - 0.30 * rec.vh)
    ok = False
    if beat is not None and not beat.failed:
        ok = await rec._safely(beat, beat.scroll_smooth(target, 1350))
    if not ok:
        await page.evaluate("(y) => window.scrollTo({ top: y, behavior: 'instant' })", target)
        await page.wait_for_timeout(500)


async def _settle_after_click(page, navigated_expected: bool) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=4000)
    except Exception:
        pass
    try:
        if await page.evaluate(_DIALOG_JS):          # a click opened a modal: close it, keep the story clean
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        if _DENY_PATH.search(urlparse(page.url).path.lower()):     # landed on login/signup/cart: step back
            await page.go_back(wait_until="domcontentloaded", timeout=6000)
    except Exception:
        pass
    try:
        await page.evaluate(_NO_POPUP_TABS_JS)
    except Exception:
        pass


async def run_story(rec, page, plan: Dict[str, Any], job_dir: Path, viewport_info: Dict[str, int],
                    page_title: str, meta_desc: str) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    site_plan = {k: plan.get(k) for k in ("brand_name", "tagline", "audience", "promise", "cards", "outro_say",
                                          "brand_rgb", "language", "source")}
    for i, step in enumerate(plan["scenes"]):
        scene_id = f"scene_{i:02d}_{_slug(step['scene_type'])}"
        try:
            await page.evaluate(_NO_POPUP_TABS_JS)
        except Exception:
            pass
        beat = await rec._begin_beat(page, job_dir, scene_id, seed=11 + 13 * i)
        await rec._pause(page, beat, 0.9 if i == 0 else 0.7)

        # 1) bring the chapter into view (site's own heading text)
        if step.get("scroll_to"):
            h = await _find(page, step["scroll_to"], False)
            if h:
                await _scroll_to_doc_y(rec, page, beat, h["docY"])
                await rec._pause(page, beat, 0.6)

        # 2) what the narrator is describing / what gets pressed - resolved on the live page
        focus = await _find(page, step.get("focus_text", ""), False)
        if focus and not focus["inView"]:
            await _scroll_to_doc_y(rec, page, beat, focus["docY"])
            await rec._pause(page, beat, 0.5)
            focus = await _find(page, step.get("focus_text", ""), False)
        target = None
        if step.get("action") == "click" and step.get("target_label"):
            target = await _find(page, step["target_label"], True)
            if target and not target["inView"]:
                await _scroll_to_doc_y(rec, page, beat, target["docY"])
                await rec._pause(page, beat, 0.5)
                target = await _find(page, step["target_label"], True)
            if target and target["covered"]:
                target = None                      # something (cookie bar / chat bubble) sits on top of it

        # 3) static fallback frame for this exact state
        s_img = job_dir / f"{scene_id}.png"
        await page.screenshot(path=str(s_img), full_page=False)
        box_for_cta = target or focus
        cta = rec._cta_from_box(box_for_cta) if box_for_cta else {"x": rec.vw // 2, "y": rec.vh // 2,
                                                                    "width": 240, "height": 60}
        real_click = bool(target and step.get("can_click") and not target.get("inForm")
                          and target.get("tag") in ("A", "BUTTON", "DIV", "SPAN", "LI"))
        if real_click and target.get("tag") == "A":
            href = (target.get("href") or "").lower()
            p = urlparse(href)
            if href and (_DENY_PATH.search(p.path.lower()) or href.startswith(("mailto:", "tel:", "javascript:"))):
                real_click = False

        sec = {
            "scene_id": scene_id, "scene_type": step["scene_type"], "title": step["title"] or page_title,
            "meta_description": step.get("goal") or meta_desc,
            "screenshot_path": str(s_img), "cta_coordinates": cta,
            "focus_area": step.get("focus_text") or step.get("target_label") or "page",
            "viewport": viewport_info, "live_clip": None,
            "interaction_performed": real_click, "target_present": bool(target),
            "plan_say": step["say"], "plan_card": step["card"],
        }
        if i == 0:
            sec["site_plan"] = site_plan
        sections.append(sec)

        # 4) choreography: rest the pointer on what is being described (no zoom), press the target (zoom)
        live = beat is not None and not beat.failed
        if live and focus:
            tag = (focus.get("tag") or "").lower()
            await rec._safely(beat, beat.scan({k: focus[k] for k in ("x", "y", "width", "height")},
                                              dwell=0.9, x_bias=0.3 if tag.startswith("h") else None))
        if live and target and not beat.failed:
            box = {k: target[k] for k in ("x", "y", "width", "height")}
            await rec._safely(beat, beat.approach(box, dwell=0.6))
            await rec._safely(beat, beat.click(perform=real_click))
        if real_click and not (beat is not None and beat.click_done):
            try:
                await page.mouse.click(cta["x"], cta["y"])      # live beat unavailable: classic instant click
            except Exception:
                pass
        if live and not beat.failed:
            beat.release_camera()
            await rec._safely(beat, beat.settle(2.3 if real_click else 1.1))
        elif real_click:
            await page.wait_for_timeout(1500)
        sec["live_clip"] = await rec._end_beat(beat)

        await _settle_after_click(page, real_click)
    return sections
