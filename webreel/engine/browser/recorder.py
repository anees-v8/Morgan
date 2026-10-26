import asyncio
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from ..config import config
from .stealth import STEALTH_SCRIPTS, COMMON_COOKIE_SELECTORS, get_stealth_headers

class BrowserRecorder:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

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
            viewport={"width": 1920, "height": 1080},
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
        """
        page: Page = await self.context.new_page()
        sections: List[Dict[str, Any]] = []

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
                        if box and 0 <= box["y"] <= 1080:
                            hero_cta = {
                                "x": int(box["x"] + box["width"] / 2),
                                "y": int(box["y"] + box["height"] / 2),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                            hero_loc = loc
                            break
                except Exception:
                    continue

            if not hero_cta:
                hero_cta = {"x": 1600, "y": 68, "width": 160, "height": 46}

            s0_img = job_dir / "scene_00_hero.png"
            await page.screenshot(path=str(s0_img), full_page=False)
            sections.append({
                "scene_id": "scene_00_hero",
                "scene_type": "hero",
                "title": page_title,
                "meta_description": meta_desc,
                "screenshot_path": str(s0_img),
                "cta_coordinates": hero_cta,
                "focus_area": "hero_cta"
            })

            # Execute real click on the Hero CTA button!
            if hero_loc:
                try:
                    await page.mouse.click(hero_cta["x"], hero_cta["y"])
                    await page.wait_for_timeout(1400)
                except Exception:
                    pass

            # Ensure viewport is in the dashboard area
            curr_y = await page.evaluate("() => window.scrollY")
            if curr_y < 200:
                await page.evaluate("() => window.scrollBy({ top: 750, behavior: 'instant' });")
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
                        if box and 0 <= box["y"] <= 1080:
                            dash_cta = {
                                "x": int(box["x"] + box["width"] / 2),
                                "y": int(box["y"] + box["height"] / 2),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                            tab_loc = loc
                            break
                except Exception:
                    continue

            if not dash_cta:
                dash_cta = {"x": 960, "y": 540, "width": 400, "height": 260}

            s1_img = job_dir / "scene_01_dashboard.png"
            await page.screenshot(path=str(s1_img), full_page=False)
            sections.append({
                "scene_id": "scene_01_dashboard",
                "scene_type": "dashboard",
                "title": "Interactive Operations Suite",
                "meta_description": "Comprehensive dashboard built for speed, scale, and automated control.",
                "screenshot_path": str(s1_img),
                "cta_coordinates": dash_cta,
                "focus_area": "center_showcase"
            })

            # Execute real click on the interactive tab to flip the DOM!
            if tab_loc:
                try:
                    await page.mouse.click(dash_cta["x"], dash_cta["y"])
                    await page.wait_for_timeout(1200)
                except Exception:
                    pass

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
                        if box and 0 <= box["y"] <= 1080:
                            pricing_cta = {
                                "x": int(box["x"] + box["width"] / 2),
                                "y": int(box["y"] + box["height"] / 2),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                            pricing_loc = loc
                            break
                except Exception:
                    continue

            if not pricing_cta:
                pricing_cta = {"x": 640, "y": 680, "width": 300, "height": 180}

            s2_img = job_dir / "scene_02_features.png"
            await page.screenshot(path=str(s2_img), full_page=False)
            sections.append({
                "scene_id": "scene_02_features",
                "scene_type": "features",
                "title": "Every Feature Built for Real Workflows",
                "meta_description": "Automated operations, instant updates, and complete transparency.",
                "screenshot_path": str(s2_img),
                "cta_coordinates": pricing_cta,
                "focus_area": "feature_card"
            })

            # Execute click on Pricing in Nav!
            if pricing_loc:
                try:
                    await page.mouse.click(pricing_cta["x"], pricing_cta["y"])
                    await page.wait_for_timeout(1800)
                except Exception:
                    pass
            else:
                # Scroll down to pricing / CTA area
                await page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight - 1080, behavior: 'instant' });")
                await page.wait_for_timeout(1000)

            # -------------------------------------------------------------
            # SCENE 3: PRICING PLANS & FINAL CONVERSION ACTION
            # -------------------------------------------------------------
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
            for sel in final_cta_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box and 0 <= box["y"] <= 1080:
                            final_cta = {
                                "x": int(box["x"] + box["width"] / 2),
                                "y": int(box["y"] + box["height"] / 2),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                            break
                except Exception:
                    continue

            if not final_cta:
                final_cta = {"x": 960, "y": 620, "width": 240, "height": 55}

            s3_img = job_dir / "scene_03_pricing.png"
            await page.screenshot(path=str(s3_img), full_page=False)
            sections.append({
                "scene_id": "scene_03_pricing",
                "scene_type": "pricing",
                "title": "Flexible Pricing & Unstoppable ROI",
                "meta_description": "Transparent plans designed to scale effortlessly with bank-grade security.",
                "screenshot_path": str(s3_img),
                "cta_coordinates": final_cta,
                "focus_area": "pricing_table"
            })

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
                "cta_coordinates": {"x": 1600, "y": 68, "width": 160, "height": 46},
                "focus_area": "hero"
            })
        finally:
            await page.close()

        return sections
