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
        Loads the website with full CSS/JS rendering, dismisses banners,
        and captures high-res 1080p viewports of each key section.
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

            # 3. Locate Primary CTA button for Hero section
            cta_locators = [
                "a:has-text('Book a Free Demo')",
                "button:has-text('Book a Free Demo')",
                "a:has-text('Get Started')",
                "button:has-text('Get Started')",
                "a:has-text('Start Free')",
                "button:has-text('Start Free')",
                "a:has-text('Explore Platform')",
                "header a[href*='demo'], header a[href*='trial']"
            ]
            hero_cta = None
            for sel in cta_locators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=300):
                        box = await loc.bounding_box()
                        if box:
                            hero_cta = {
                                "x": int(box["x"] + box["width"] / 2),
                                "y": int(box["y"] + box["height"] / 2),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                            break
                except Exception:
                    continue

            if not hero_cta:
                hero_cta = {"x": 1600, "y": 68, "width": 160, "height": 46}

            # 4. Capture Section 0: Hero Viewport (Top: 0)
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

            # 5. Smooth scroll to Section 1: Dashboard / Core Feature
            # Scroll down ~750px to reveal the interactive dashboard & product showcase
            await page.evaluate("() => window.scrollBy({ top: 750, behavior: 'instant' });")
            await page.wait_for_timeout(800)
            s1_img = job_dir / "scene_01_dashboard.png"
            await page.screenshot(path=str(s1_img), full_page=False)
            sections.append({
                "scene_id": "scene_01_dashboard",
                "scene_type": "dashboard",
                "title": "Interactive Product Suite",
                "meta_description": "Comprehensive dashboard built for speed, scale and automated control.",
                "screenshot_path": str(s1_img),
                "cta_coordinates": {"x": 960, "y": 540, "width": 400, "height": 260},
                "focus_area": "center_showcase"
            })

            # 6. Smooth scroll to Section 2: Features Grid
            await page.evaluate("() => window.scrollBy({ top: 750, behavior: 'instant' });")
            await page.wait_for_timeout(800)
            s2_img = job_dir / "scene_02_features.png"
            await page.screenshot(path=str(s2_img), full_page=False)
            sections.append({
                "scene_id": "scene_02_features",
                "scene_type": "features",
                "title": "Every Feature Built for Real Workflows",
                "meta_description": "Automated operations, instant updates, and complete transparency.",
                "screenshot_path": str(s2_img),
                "cta_coordinates": {"x": 640, "y": 680, "width": 300, "height": 180},
                "focus_area": "feature_card"
            })

            # 7. Check if there is a separate Pricing or Features page in navigation
            nav_links = await page.eval_on_selector_all(
                "nav a[href], header a[href]",
                "elements => elements.map(e => ({ href: e.href, text: e.innerText.trim() }))"
            )
            
            pricing_url = None
            features_url = None
            for l in nav_links:
                text_lower = l.get("text", "").lower()
                href_lower = l.get("href", "").lower()
                if "pricing" in text_lower or "pricing" in href_lower:
                    pricing_url = l.get("href")
                elif "feature" in text_lower or "feature" in href_lower:
                    features_url = l.get("href")

            # 8. If Pricing page exists, visit and capture it; otherwise scroll to bottom CTA section
            if pricing_url and pricing_url != url:
                try:
                    await page.goto(pricing_url, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(1500)
                    s3_img = job_dir / "scene_03_pricing.png"
                    await page.screenshot(path=str(s3_img), full_page=False)
                    sections.append({
                        "scene_id": "scene_03_pricing",
                        "scene_type": "pricing",
                        "title": "Flexible Pricing & Plans",
                        "meta_description": "Transparent plans designed to scale effortlessly with your institute.",
                        "screenshot_path": str(s3_img),
                        "cta_coordinates": {"x": 960, "y": 620, "width": 220, "height": 50},
                        "focus_area": "pricing_table"
                    })
                except Exception:
                    pass

            if len(sections) < 4:
                # Scroll to bottom CTA section
                await page.evaluate("() => window.scrollTo({ top: document.body.scrollHeight - 1080, behavior: 'instant' });")
                await page.wait_for_timeout(800)
                s3_img = job_dir / "scene_03_bottom_cta.png"
                await page.screenshot(path=str(s3_img), full_page=False)
                sections.append({
                    "scene_id": "scene_03_bottom_cta",
                    "scene_type": "pricing",
                    "title": "Start Your Transformation",
                    "meta_description": "Book a live 1-on-1 demo or explore the platform free today.",
                    "screenshot_path": str(s3_img),
                    "cta_coordinates": {"x": 960, "y": 500, "width": 260, "height": 55},
                    "focus_area": "bottom_cta"
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
