"""
Site Brief: everything the story director may know about a website, extracted from the live page.

  - headings + the paragraph under each (the site's own vocabulary)
  - every visible button / link / tab, each classified as safe-to-really-click or "show a press only"
  - prices / stats with their surrounding sentence (the only numbers a script may quote)
  - brand colour (what the site's own buttons are painted with)
  - screenshots (so a vision model can OCR text that lives inside images / UI mockups)

Extraction happens on a separate "scout" page so the page that gets recorded stays pristine
(scroll-reveal animations still play live when the camera scrolls to them).
"""
import asyncio
import colorsys
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urldefrag

from ..browser.crawler import IGNORE_PATTERNS, categorize_link, score_link

BRIEF_JS = r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 4 && r.height > 4 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05;
  };
  const docY = e => e.getBoundingClientRect().top + scrollY;
  const meta = n => { const m = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`); return m ? norm(m.content) : ''; };
  const skipArea = e => !!e.closest('[role=dialog],[aria-modal=true],[id*=cookie i],[class*=cookie i],[class*=consent i],[id*=onetrust i]');

  // ---------- headings (+ the text right under each)
  const headings = [], seenH = new Set();
  for (const h of document.querySelectorAll('h1,h2,h3,h4')) {
    if (!visible(h) || skipArea(h)) continue;
    const text = norm(h.innerText);
    if (text.length < 3 || text.length > 140 || seenH.has(text)) continue;
    seenH.add(text);
    let blurb = '';
    let n = h.nextElementSibling;
    for (let i = 0; i < 3 && n && !blurb; i++, n = n.nextElementSibling) {
      if (n.matches('h1,h2,h3,h4')) break;
      const t = norm(n.innerText);
      if (t.length > 20) blurb = t.slice(0, 320);
    }
    if (!blurb && h.parentElement) {
      const p = h.parentElement.querySelector('p');
      if (p && !p.contains(h)) blurb = norm(p.innerText).slice(0, 320);
    }
    headings.push({level: +h.tagName[1], text, blurb, y: Math.round(docY(h))});
    if (headings.length >= 60) break;
  }

  // ---------- clickable things
  const actions = [], seenA = new Set();
  for (const e of document.querySelectorAll('a[href], button, [role=button], [role=tab], [role=link]')) {
    if (!visible(e) || skipArea(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 24 || r.height < 14 || r.width > vw * 0.85) continue;
    const label = norm(e.getAttribute('aria-label') || e.innerText || e.title || '');
    if (!label || label.length > 42) continue;
    const key = label.toLowerCase() + '|' + (e.href || '');
    if (seenA.has(key)) continue;
    seenA.add(key);
    const cs = getComputedStyle(e);
    actions.push({
      label, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '',
      href: e.href || '', inNav: !!e.closest('nav, header, [role=navigation]'), inForm: !!e.closest('form'), inFooter: !!e.closest('footer, [role=contentinfo]'),
      type: e.type || '', blank: e.target === '_blank', download: e.hasAttribute('download'),
      y: Math.round(docY(e)), w: Math.round(r.width), h: Math.round(r.height),
      bg: cs.backgroundColor, color: cs.color,
    });
    if (actions.length >= 140) break;
  }

  // ---------- numbers with context (prices, stats)
  const bodyText = norm((document.querySelector('main') || document.body).innerText);
  const nums = [], seenN = new Set();
  const re = /(?:₹|\$|€|£|Rs\.?\s?)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:\/|per)\s?[a-zA-Z]{2,20}(?:\s[a-zA-Z]{2,12})?)?|\b\d[\d,]*(?:\.\d+)?\s?(?:%|\+|x\b|k\b|K\b|M\b|million|billion|hours?|minutes?|seconds?|days?|users?|customers?|teams?|students?|schools?|countries)/g;
  let m;
  while ((m = re.exec(bodyText)) && nums.length < 40) {
    const value = norm(m[0]);
    if (seenN.has(value)) continue;
    seenN.add(value);
    nums.push({value, context: bodyText.slice(Math.max(0, m.index - 60), Math.min(bodyText.length, m.index + m[0].length + 60))});
  }

  // ---------- colour hints
  const vars = {};
  const rs = getComputedStyle(document.documentElement);
  for (const v of ['--primary', '--brand', '--accent', '--color-primary', '--primary-color', '--brand-color', '--theme-color']) {
    const val = rs.getPropertyValue(v).trim();
    if (val) vars[v] = val;
  }

  return {
    url: location.href, title: document.title, lang: document.documentElement.lang || '',
    meta: {description: meta('description'), ogTitle: meta('og:title'), ogSite: meta('og:site_name'),
           ogDescription: meta('og:description'), themeColor: meta('theme-color')},
    headings, actions, numbers: nums, cssVars: vars,
    bodyText: bodyText.slice(0, 7000),
    pageHeight: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
    viewport: {w: vw, h: vh},
  };
}
"""

DENY_LABEL = re.compile(
    r"\b(log ?in|sign ?in|sign ?up|register|buy|purchase|checkout|cart|log ?out|sign ?out|delete|remove|"
    r"download|install|pay|submit|send|subscribe|apply|join waitlist|get app|open app)\b", re.I)
CTA_LABEL = re.compile(
    r"\b(get started|start|try|book|demo|free|contact|talk|join|request|schedule|explore|learn more|see|watch|view)\b", re.I)
DENY_SCHEMES = ("mailto:", "tel:", "javascript:", "sms:", "whatsapp:")
# Pages that are real but make a poor chapter of a product film.
AVOID_STORY = re.compile(r"(contact|career|jobs?|press|privacy|terms|legal|cookie|support|help|status|sitemap|partner-?program)", re.I)


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _path(url: str) -> str:
    p = urlparse(url).path or "/"
    return p.rstrip("/") or "/"


def _parse_rgb(css: str) -> Optional[Tuple[int, int, int, float]]:
    css = (css or "").strip()
    m = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)", css)
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), a
    m = re.match(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", css)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    return None


def _saturation_lightness(rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return h, s, l


def classify_action(a: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """Adds kind + can_click (a *real* click is safe) to one extracted clickable."""
    label = a["label"]
    href = (a.get("href") or "").strip()
    tag, role = a["tag"], a.get("role", "")
    low = href.lower()
    out = dict(a)

    same_site = bool(href) and low.startswith(("http://", "https://")) and _host(href) == _host(base_url)
    ignored_path = any(re.search(p, _path(href).lower()) for p in IGNORE_PATTERNS) if href else False
    hash_only = bool(href) and urldefrag(href)[0].rstrip("/") == urldefrag(base_url)[0].rstrip("/") and "#" in href

    if label.endswith("?"):
        kind = "faq"                      # accordion questions: never a story target
    elif role == "tab":
        kind = "tab"
    elif a.get("inNav") and (tag == "a" or role == "link") and same_site:
        kind = "nav"
    elif CTA_LABEL.search(label) and len(label) <= 32 and not a.get("inNav"):
        kind = "cta"
    elif tag == "a" or role == "link":
        kind = "link"
    else:
        kind = "button"

    can_click = False
    if DENY_LABEL.search(label) or low.startswith(DENY_SCHEMES) or a.get("download") or a.get("inForm"):
        can_click = False
    elif tag == "a" or role == "link":
        can_click = same_site and not ignored_path and not a.get("blank") or hash_only
    elif role == "tab":
        can_click = True
    elif tag == "button" or role == "button":
        # (a <button> reports type="submit" by default; only a *form* makes that matter, handled above)
        can_click = True
    story_ok = (kind != "faq" and not a.get("inFooter") and not AVOID_STORY.search(label)
                and not (href and AVOID_STORY.search(_path(href))))
    out.update(kind=kind, can_click=bool(can_click), story_ok=bool(story_ok),
               nav_category=categorize_link(href, label) if href else "general")
    return out


def pick_brand_color(raw: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    """The colour the site paints its own call-to-action buttons with (falls back to theme-color / CSS vars)."""
    votes: Dict[Tuple[int, int, int], float] = {}
    for a in raw.get("actions", []):
        c = _parse_rgb(a.get("bg", ""))
        if not c or c[3] < 0.9:
            continue
        rgb = c[:3]
        _, s, l = _saturation_lightness(rgb)
        if s < 0.28 or l < 0.14 or l > 0.86:
            continue
        key = (rgb[0] // 8 * 8, rgb[1] // 8 * 8, rgb[2] // 8 * 8)
        votes[key] = votes.get(key, 0.0) + (a["w"] * a["h"]) ** 0.5 * (2.0 if CTA_LABEL.search(a["label"]) else 1.0)
    if votes:
        return max(votes, key=votes.get)
    cands = [raw.get("meta", {}).get("themeColor", "")] + list(raw.get("cssVars", {}).values())
    for css in cands:
        c = _parse_rgb(css)
        if c:
            _, s, l = _saturation_lightness(c[:3])
            if s >= 0.25 and 0.14 <= l <= 0.88:
                return c[:3]
    return None


def postprocess(raw: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    actions = [classify_action(a, base_url) for a in raw.get("actions", [])]
    # keep the useful ones first: tabs, nav pages, CTAs, then the rest
    order = {"tab": 0, "nav": 1, "cta": 2, "button": 3, "link": 4}
    actions.sort(key=lambda a: (order.get(a["kind"], 5), a["y"]))
    brand_rgb = pick_brand_color(raw)
    meta = raw.get("meta", {})
    name = meta.get("ogSite") or ""
    if not name:
        t = raw.get("title", "")
        parts = [p.strip() for p in re.split(r"\s[|\-–—:•]\s", t) if p.strip()]
        name = min(parts, key=len) if parts else _host(base_url).split(".")[0].title()
    return {
        "url": raw.get("url", base_url), "host": _host(base_url), "title": raw.get("title", ""),
        "lang": raw.get("lang", ""), "brand_name": name, "meta": meta,
        "headings": raw.get("headings", []), "actions": actions, "numbers": raw.get("numbers", []),
        "brand_rgb": list(brand_rgb) if brand_rgb else None,
        "body_text": raw.get("bodyText", ""), "page_height": raw.get("pageHeight", 0),
    }


async def _dismiss_cookie_banner(page) -> None:
    from ..browser.stealth import COMMON_COOKIE_SELECTORS
    for selector in COMMON_COOKIE_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=300):
                await btn.click()
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


async def _load(page, url: str) -> None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=25000)
    except Exception:
        try:
            await page.goto(url, wait_until="load", timeout=20000)
        except Exception:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(1200)
    try:
        await page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
    except Exception:
        pass


async def scout_page(context, url: str, shots: int = 3, shot_quality: int = 72) -> Dict[str, Any]:
    """Open `url` in a throw-away page: extract the brief and take JPEG screenshots down the page."""
    page = await context.new_page()
    try:
        await _load(page, url)
        await _dismiss_cookie_banner(page)
        raw = await page.evaluate(BRIEF_JS)
        brief = postprocess(raw, page.url)
        images: List[bytes] = []
        if shots:
            vh = (raw.get("viewport") or {}).get("h", 800)
            height = max(raw.get("pageHeight", vh), vh)
            for i in range(shots):
                y = int(i * vh * 0.95)
                if i and y > height - vh * 0.6:
                    break
                try:
                    await page.evaluate("(y) => window.scrollTo(0, y)", y)
                    await page.wait_for_timeout(450)
                    images.append(await page.screenshot(type="jpeg", quality=shot_quality))
                except Exception:
                    break
        brief["screenshots"] = images
        return brief
    finally:
        await page.close()


def pick_subpages(brief: Dict[str, Any], limit: int = 2) -> List[Dict[str, Any]]:
    """The site's own high-value pages (pricing / features / demo) reachable from its navigation."""
    here = _path(brief["url"])
    seen, picked = {here}, []
    editorial = re.compile(r"(blog|guide|docs?|learn|resource|article|news|case-stud|customers?/|stories|webinar|ebook)", re.I)
    cands = [a for a in brief["actions"] if a.get("can_click") and a.get("story_ok") and a["tag"] == "a" and a.get("href")
             and a["nav_category"] in ("pricing", "features", "demo")
             and not editorial.search(_path(a["href"])) and not editorial.search(a["label"])]
    cands.sort(key=lambda a: -score_link(a["href"], a["label"]))
    for a in cands:
        p = _path(a["href"])
        if p in seen or "#" in a["href"] and urldefrag(a["href"])[0].rstrip("/") == brief["url"].rstrip("/"):
            continue
        seen.add(p)
        picked.append(a)
        if len(picked) >= limit:
            break
    return picked


async def build_site_brief(context, url: str, max_subpages: int = 2) -> Dict[str, Any]:
    """Home page (with screenshots) + its pricing/features pages (text only), scouted in parallel."""
    home = await scout_page(context, url, shots=3)
    subs = pick_subpages(home, max_subpages)

    async def one(a):
        try:
            b = await asyncio.wait_for(scout_page(context, a["href"], shots=0), timeout=45)
            b["via_label"] = a["label"]
            b["category"] = a["nav_category"]
            return b
        except Exception:
            return None

    pages = [p for p in await asyncio.gather(*[one(a) for a in subs]) if p]
    home["pages"] = pages
    return home
