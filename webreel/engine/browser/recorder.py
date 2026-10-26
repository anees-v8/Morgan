import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from ..config import config
from .stealth import STEALTH_SCRIPTS, COMMON_COOKIE_SELECTORS, get_stealth_headers
from .live_capture import LiveBeat

logger = logging.getLogger("webreel.live")

# The classic journey was authored against a 1920x1080 viewport; fallback targets are kept in
# that space and scaled to whatever viewport we actually capture at.
_REF_W, _REF_H = 1920.0, 1080.0


class BrowserRecorder:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.vw: int = int(config.capture_width)
        self.vh: int = int(config.capture_height)
        self.cdp = None
        self.cursor_pos: Tuple[float, float] = (self.vw * 0.60, self.vh * 0.86)

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--hide-scrollbars",
                "--mute-audio"
            ]
        )
        self.context = await self.browser.new_context(
            viewport={"width": self.vw, "height": self.vh},
            user_agent=config.user_agent,
            device_scale_factor=1,
            extra_http_headers=get_stealth_headers()
        )
        await self.context.add_init_script(STEALTH_SCRIPTS)

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ------------------------------------------------------------------
    # Live choreography helpers (all best-effort: failure => classic behaviour)
    # ------------------------------------------------------------------
    def _fb(self, x: float, y: float, w: float, h: float) -> Dict[str, int]:
        """Scale a reference-space (1920x1080) fallback target into the capture viewport."""
        sx, sy = self.vw / _REF_W, self.vh / _REF_H
        return {"x": int(x * sx), "y": int(y * sy), "width": int(w * sx), "height": int(h * sy)}

    def _cta_from_box(self, box: Dict[str, float]) -> Dict[str, int]:
        return {
            "x": int(box["x"] + box["width"] / 2),
            "y": int(box["y"] + box["height"] / 2),
            "width": int(box["width"]),
            "height": int(box["height"])
        }

    async def _begin_beat(self, page: Page, job_dir: Path, scene_id: str, seed: int) -> Optional[LiveBeat]:
        if not config.live_capture or self.cdp is None:
            return None
        try:
            beat = LiveBeat(page, self.cdp, job_dir, scene_id, (self.vw, self.vh), self.cursor_pos, seed=seed)
            await beat.start()
            return beat
        except Exception as e:
            logger.warning("live capture could not start for %s: %r (falling back to screenshot)", scene_id, e)
            return None

    async def _end_beat(self, beat: Optional[LiveBeat]) -> Optional[str]:
        if beat is None:
            return None
        try:
            path = await beat.stop()
            if beat.failed or path is None:
                logger.warning("live capture for %s unusable (frames=%d, failed=%s, error=%r); using screenshot",
                               beat.scene_id, len(beat.frame_times), beat.failed, beat.error)
                return None
            self.cursor_pos = beat.pos
            return str(path)
        except Exception as e:
            logger.warning("live capture for %s failed to finalise: %r", beat.scene_id, e)
            return None

    @staticmethod
    async def _safely(beat: Optional[LiveBeat], coro) -> bool:
        """Run a beat coroutine; any failure poisons the beat (classic path takes over)."""
        if beat is None or beat.failed:
            coro.close()
            return False
        try:
            await coro
            return True
        except Exception as e:
            beat.failed = True
            beat.error = repr(e)
            logger.warning("live beat %s aborted: %r", beat.scene_id, e)
            return False

    async def _pause(self, page: Page, beat: Optional[LiveBeat], seconds: float):
        """A pause that is also recorded live when a beat is running."""
        if beat is not None and not beat.failed:
            await self._safely(beat, beat.hold(seconds))
        else:
            await page.wait_for_timeout(int(seconds * 1000))

    async def _scroll(self, page: Page, beat: Optional[LiveBeat], dy: float):
        """Relative scroll: smooth + captured live, or the classic instant jump."""
        ok = await self._safely(beat, beat.scroll_by_smooth(dy, 1350)) if beat else False
        if not ok:
            await page.evaluate("(dy) => window.scrollBy({ top: dy, behavior: 'instant' });", dy)

    async def _scan_hovers(self, page: Page, beat: Optional[LiveBeat], cta: Dict[str, int], count: int):
        """Reader-style hovers over headings / hero media while the narrator talks."""
        if beat is None or beat.failed or count <= 0:
            return
        try:
            anchors = await beat.find_anchors()
        except Exception:
            return
        order = anchors.get("headings", [])[:1] + anchors.get("media", [])[:1] + \
            anchors.get("copy", [])[:1] + anchors.get("headings", [])[1:2]
        chosen: List[Dict[str, float]] = []
        for a in order:
            if len(chosen) >= count:
                break
            acx, acy = a["x"] + a["width"] / 2, a["y"] + a["height"] / 2
            contains_target = a["x"] <= cta["x"] <= a["x"] + a["width"] and a["y"] <= cta["y"] <= a["y"] + a["height"]
            if contains_target and a["width"] * a["height"] < 0.5 * self.vw * self.vh:
                continue
            if chosen and abs(acx - (chosen[-1]["x"] + chosen[-1]["width"] / 2)) + \
                    abs(acy - (chosen[-1]["y"] + chosen[-1]["height"] / 2)) < 140:
                continue
            chosen.append(a)
        for i, a in enumerate(chosen):
            bias = 0.38 if a.get("tag", "").lower().startswith("h") else None
            ok = await self._safely(beat, beat.scan(a, dwell=0.8 if i == 0 else 0.7, x_bias=bias))
            if not ok:
                return

    async def _act_on_target(
        self,
        page: Page,
        beat: Optional[LiveBeat],
        cta: Dict[str, int],
        loc: Any,
        perform_click: bool,
        post_wait_ms: int,
        scans: int = 1,
    ):
        """
        Approach -> hover -> press -> let the page react, all recorded live. If the live beat
        is unavailable (or breaks half-way) we perform the classic instant click instead, so the
        journey (and therefore every later scene) is always identical to the non-live flow.
        """
        box = {"x": cta["x"] - cta["width"] / 2.0, "y": cta["y"] - cta["height"] / 2.0,
               "width": float(cta["width"]), "height": float(cta["height"])}
        live_ok = beat is not None and not beat.failed
        if live_ok:
            await self._scan_hovers(page, beat, cta, scans)
        # Only ever travel to a *real* element; fallback coordinates are guesses.
        if live_ok and not beat.failed and loc is not None:
            await self._safely(beat, beat.approach(box, dwell=0.55))

        if loc is not None:
            if perform_click:
                if beat is not None and not beat.failed:
                    await self._safely(beat, beat.click(perform=True))
                if not (beat is not None and beat.click_done):
                    try:
                        await page.mouse.click(cta["x"], cta["y"])
                    except Exception:
                        pass
            elif beat is not None and not beat.failed:
                # Pricing/conversion: the page is *not* clicked (it would navigate away) but the
                # viewer still sees the pointer press the button.
                await self._safely(beat, beat.click(perform=False))

        if beat is not None and not beat.failed:
            beat.release_camera()
            await self._safely(beat, beat.settle(post_wait_ms / 1000.0 + 0.9))
        elif perform_click and loc is not None:
            await page.wait_for_timeout(post_wait_ms)

    async def _plan_story(self, url: str, job_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Scout the site (its own text, buttons, numbers, brand colour + screenshots) and let the
        StoryDirector plan the film from it. Returns None if anything goes wrong, in which case the
        classic journey runs instead.
        """
        from ..ai.site_brief import build_site_brief
        from ..ai.story_director import StoryDirector
        t0 = time.perf_counter()
        brief = await asyncio.wait_for(build_site_brief(self.context, url), timeout=100)
        t1 = time.perf_counter()
        plan = await StoryDirector().plan(brief)
        plan["timings"] = {"scout_s": round(t1 - t0, 1), "director_s": round(time.perf_counter() - t1, 1)}
        logger.info("story plan ready: scout %.1fs, director %.1fs (%s)", t1 - t0, time.perf_counter() - t1, plan.get("source"))
        try:
            (job_dir / "story_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        return plan

    async def capture_page_sections(
        self,
        url: str,
        job_dir: Path
    ) -> List[Dict[str, Any]]:
        """
        Executes an Autonomous Interactive Action Journey:
        - Hero: Locates primary CTA button, captures pristine hero, then clicks CTA!
        - Dashboard: Captures transitioned screen, locates interactive tab/card, clicks tab!
        - Deep Features: Captures flipped tab state, locates pricing/nav link, clicks nav!
        - Pricing/Conversion: Captures loaded pricing tiers, targets conversion CTA!
        Every screenshot reflects the real consequences of previous clicks.

        Additionally (live capture): each scene is recorded as a timestamped ~60fps frame
        stream with a human-like pointer choreography, referenced by `live_clip`. The static
        `screenshot_path` is still produced for every scene and remains the fallback.
        """
        page: Page = await self.context.new_page()
        sections: List[Dict[str, Any]] = []
        vw, vh = self.vw, self.vh
        viewport_info = {"width": vw, "height": vh}

        self.cdp = None
        if config.live_capture:
            try:
                self.cdp = await self.context.new_cdp_session(page)
            except Exception:
                self.cdp = None

        try:
            # 1. Navigate and wait for all CSS/JS assets to load completely
            try:
                await page.goto(url, wait_until="networkidle", timeout=40000)
            except Exception:
                await page.goto(url, wait_until="load", timeout=30000)

            # Wait for web fonts & CSS rendering
            await page.wait_for_timeout(2000)
            await page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
            # Prevent link clicks from opening separate popup tabs
            await page.evaluate("() => document.querySelectorAll('a[target=\"_blank\"]').forEach(a => a.removeAttribute('target'))")

            # 2. Dismiss cookie / privacy banners
            for selector in COMMON_COOKIE_SELECTORS:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        await page.wait_for_timeout(400)
                        break
                except Exception:
                    pass

            page_title = await page.title()

            # Extract meta description
            meta_desc = ""
            desc_tag = page.locator("meta[name='description'], meta[property='og:description']").first
            try:
                if await desc_tag.count() > 0:
                    meta_desc = await desc_tag.get_attribute("content") or ""
            except Exception:
                pass

            # -------------------------------------------------------------
            # DYNAMIC STORY: plan the film from this site's own content, then perform it.
            # (The fixed legacy journey below is only the fallback.)
            # -------------------------------------------------------------
            if config.dynamic_story:
                dyn: List[Dict[str, Any]] = []
                try:
                    plan = await self._plan_story(url, job_dir)
                    if plan and plan.get("scenes"):
                        from .story_runner import run_story
                        dyn = await run_story(self, page, plan, job_dir, viewport_info, page_title, meta_desc)
                except Exception as e:
                    logger.warning("dynamic story failed (%r); falling back to the classic journey", e)
                    dyn = []
                if dyn:
                    return dyn
                # nothing usable was recorded: restart from a clean page for the classic journey
                try:
                    await page.goto(url, wait_until="load", timeout=30000)
                    await page.wait_for_timeout(1500)
                    await page.evaluate("() => document.querySelectorAll('a[target=\"_blank\"]').forEach(a => a.removeAttribute('target'))")
                except Exception:
                    pass

            # -------------------------------------------------------------
            # SCENE 0: HERO VIEWPORT & PRIMARY CTA ACTION
            # -------------------------------------------------------------
            cta_locators = [
                "a:has-text('Explore Platform')",
                "button:has-text('Explore Platform')",
                "a:has-text('Get Started')",
                "button:has-text('Get Started')",
                "a:has-text('Start Free')",
                "button:has-text('Start Free')",
                "a:has-text('Book a Free Demo')",
                "button:has-text('Book a Free Demo')",
                "header a[href*='demo'], header a[href*='trial']",
                "a.cta, button.cta"
            ]
            hero_cta = None
            hero_loc = None
            for sel in cta_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box and 0 <= box["y"] <= vh:
                            hero_cta = self._cta_from_box(box)
                            hero_loc = loc
                            break
                except Exception:
                    continue

            if not hero_cta:
                hero_cta = self._fb(1600, 68, 160, 46)

            beat0 = await self._begin_beat(page, job_dir, "scene_00_hero", seed=11)
            await self._pause(page, beat0, 0.9)

            s0_img = job_dir / "scene_00_hero.png"
            await page.screenshot(path=str(s0_img), full_page=False)
            sec0 = {
                "scene_id": "scene_00_hero",
                "scene_type": "hero",
                "title": page_title,
                "meta_description": meta_desc,
                "screenshot_path": str(s0_img),
                "cta_coordinates": hero_cta,
                "focus_area": "hero_cta",
                "viewport": viewport_info,
                "live_clip": None,
                "interaction_performed": bool(hero_loc)
            }
            sections.append(sec0)

            # Execute real click on the Hero CTA button!
            try:
                await self._act_on_target(page, beat0, hero_cta, hero_loc, perform_click=bool(hero_loc),
                                          post_wait_ms=1400, scans=3)
            except Exception:
                pass
            sec0["live_clip"] = await self._end_beat(beat0)

            # Ensure viewport is in the dashboard area
            curr_y = await page.evaluate("() => window.scrollY")
            beat1 = await self._begin_beat(page, job_dir, "scene_01_dashboard", seed=23)
            await self._pause(page, beat1, 0.7)
            if curr_y < 200:
                await self._scroll(page, beat1, 750)
                if beat1 is not None and not beat1.failed:
                    await self._pause(page, beat1, 0.9)
                else:
                    await page.wait_for_timeout(800)

            # -------------------------------------------------------------
            # SCENE 1: CORE DASHBOARD & INTERACTIVE TAB SWITCHER
            # -------------------------------------------------------------
            tab_locators = [
                "button:has-text('Teachers')",
                "text='Teachers & Staff'",
                "button:has-text('Staff')",
                "[role='tab']",
                "button[data-state]",
                ".tab-btn",
                "button:has-text('Students')",
                "button:has-text('Features')"
            ]
            dash_cta = None
            tab_loc = None
            for sel in tab_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box and 0 <= box["y"] <= vh:
                            dash_cta = self._cta_from_box(box)
                            tab_loc = loc
                            break
                except Exception:
                    continue

            if not dash_cta:
                dash_cta = self._fb(960, 540, 400, 260)

            s1_img = job_dir / "scene_01_dashboard.png"
            await page.screenshot(path=str(s1_img), full_page=False)
            sec1 = {
                "scene_id": "scene_01_dashboard",
                "scene_type": "dashboard",
                "title": "Interactive Operations Suite",
                "meta_description": "Comprehensive dashboard built for speed, scale, and automated control.",
                "screenshot_path": str(s1_img),
                "cta_coordinates": dash_cta,
                "focus_area": "center_showcase",
                "viewport": viewport_info,
                "live_clip": None,
                "interaction_performed": bool(tab_loc)
            }
            sections.append(sec1)

            # Execute real click on the interactive tab to flip the DOM!
            try:
                await self._act_on_target(page, beat1, dash_cta, tab_loc, perform_click=bool(tab_loc),
                                          post_wait_ms=1200, scans=2)
            except Exception:
                pass
            sec1["live_clip"] = await self._end_beat(beat1)

            # -------------------------------------------------------------
            # SCENE 2: FEATURE DEEP DIVE & NAVIGATION TO PRICING
            # -------------------------------------------------------------
            nav_locators = [
                "nav a:has-text('Pricing')",
                "header a:has-text('Pricing')",
                "a:has-text('Pricing')",
                "nav a:has-text('Features')",
                "header a:has-text('Features')"
            ]
            pricing_cta = None
            pricing_loc = None
            for sel in nav_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box and 0 <= box["y"] <= vh:
                            pricing_cta = self._cta_from_box(box)
                            pricing_loc = loc
                            break
                except Exception:
                    continue

            if not pricing_cta:
                pricing_cta = self._fb(640, 680, 300, 180)

            beat2 = await self._begin_beat(page, job_dir, "scene_02_features", seed=37)
            await self._pause(page, beat2, 0.9)

            s2_img = job_dir / "scene_02_features.png"
            await page.screenshot(path=str(s2_img), full_page=False)
            sec2 = {
                "scene_id": "scene_02_features",
                "scene_type": "features",
                "title": "Every Feature Built for Real Workflows",
                "meta_description": "Automated operations, instant updates, and complete transparency.",
                "screenshot_path": str(s2_img),
                "cta_coordinates": pricing_cta,
                "focus_area": "feature_card",
                "viewport": viewport_info,
                "live_clip": None,
                "interaction_performed": bool(pricing_loc)
            }
            sections.append(sec2)

            # Execute click on Pricing in Nav!
            scroll_to_bottom_next = False
            try:
                if pricing_loc:
                    await self._act_on_target(page, beat2, pricing_cta, pricing_loc, perform_click=True,
                                              post_wait_ms=1800, scans=2)
                else:
                    # No nav link to click: just let the reader-hovers play out; the page is
                    # scrolled to the pricing/CTA area at the start of the next scene.
                    scroll_to_bottom_next = True
                    await self._act_on_target(page, beat2, pricing_cta, None, perform_click=False,
                                              post_wait_ms=400, scans=2)
            except Exception:
                pass
            sec2["live_clip"] = await self._end_beat(beat2)

            # -------------------------------------------------------------
            # SCENE 3: PRICING PLANS & FINAL CONVERSION ACTION
            # -------------------------------------------------------------
            beat3 = await self._begin_beat(page, job_dir, "scene_03_pricing", seed=41)
            await self._pause(page, beat3, 0.8)
            if scroll_to_bottom_next:
                # Original behaviour (jump to the bottom), now eased and captured live.
                bottom = await page.evaluate("(h) => Math.max(0, document.body.scrollHeight - h)", vh)
                ok = False
                if beat3 is not None and not beat3.failed:
                    ok = await self._safely(beat3, beat3.scroll_smooth(bottom, 1500))
                if ok:
                    await self._pause(page, beat3, 0.7)
                else:
                    await page.evaluate("(h) => window.scrollTo({ top: document.body.scrollHeight - h, behavior: 'instant' });", vh)
                    await page.wait_for_timeout(1000)

            final_cta_locators = [
                "button:has-text('Get Started')",
                "a:has-text('Book a Free Demo')",
                "button:has-text('Book a Free Demo')",
                "a:has-text('Contact Sales')",
                "button:has-text('Contact Sales')",
                "a:has-text('Start Free')",
                "button:has-text('Start Free')",
                "button:has-text('Subscribe')",
                "a:has-text('Sign up')"
            ]
            final_cta = None
            final_loc = None
            for sel in final_cta_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box and 0 <= box["y"] <= vh:
                            final_cta = self._cta_from_box(box)
                            final_loc = loc
                            break
                except Exception:
                    continue

            if not final_cta:
                final_cta = self._fb(960, 620, 240, 55)

            s3_img = job_dir / "scene_03_pricing.png"
            await page.screenshot(path=str(s3_img), full_page=False)
            sec3 = {
                "scene_id": "scene_03_pricing",
                "scene_type": "pricing",
                "title": "Flexible Pricing & Unstoppable ROI",
                "meta_description": "Transparent plans designed to scale effortlessly with bank-grade security.",
                "screenshot_path": str(s3_img),
                "cta_coordinates": final_cta,
                "focus_area": "pricing_table",
                "viewport": viewport_info,
                "live_clip": None,
                "interaction_performed": False
            }
            sections.append(sec3)

            # Final CTA is only *pointed at and pressed visually* (never navigates away).
            try:
                await self._act_on_target(page, beat3, final_cta, final_loc, perform_click=False,
                                          post_wait_ms=700, scans=2)
            except Exception:
                pass
            sec3["live_clip"] = await self._end_beat(beat3)

        except Exception as e:
            # Fallback capture
            s0_img = job_dir / "scene_00_hero.png"
            await page.screenshot(path=str(s0_img), full_page=False)
            sections.append({
                "scene_id": "scene_00_hero",
                "scene_type": "hero",
                "title": "Product Overview",
                "meta_description": "Experience the modern platform.",
                "screenshot_path": str(s0_img),
                "cta_coordinates": self._fb(1600, 68, 160, 46),
                "focus_area": "hero",
                "viewport": viewport_info,
                "live_clip": None,
                "interaction_performed": False
            })
        finally:
            try:
                if self.cdp is not None:
                    await self.cdp.detach()
            except Exception:
                pass
            await page.close()

        return sections
