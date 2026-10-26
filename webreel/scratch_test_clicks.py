import asyncio
from playwright.async_api import async_playwright

async def test_real_clicks():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await page.goto("https://campusweb.co.in", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # 1. Click Explore Platform
        btn = page.locator("text='Explore Platform'").first
        if await btn.is_visible():
            box = await btn.bounding_box()
            print("Explore Platform box:", box)
            await page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2, steps=10)
            await page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            await page.wait_for_timeout(1000)
            await page.screenshot(path="after_explore_click.png")
            print("Saved after_explore_click.png")
            
        # 2. Click Teachers & Staff tab
        tab = page.locator("text='Teachers & Staff'").first
        if await tab.is_visible():
            tbox = await tab.bounding_box()
            print("Teachers & Staff tab box:", tbox)
            await page.mouse.move(tbox["x"] + tbox["width"]/2, tbox["y"] + tbox["height"]/2, steps=10)
            await page.mouse.click(tbox["x"] + tbox["width"]/2, tbox["y"] + tbox["height"]/2)
            await page.wait_for_timeout(1000)
            await page.screenshot(path="after_tab_click.png")
            print("Saved after_tab_click.png")

        # 3. Click Pricing in header
        pricing_nav = page.locator("nav a:has-text('Pricing'), header a:has-text('Pricing')").first
        if await pricing_nav.is_visible():
            pbox = await pricing_nav.bounding_box()
            print("Pricing nav box:", pbox)
            await page.mouse.move(pbox["x"] + pbox["width"]/2, pbox["y"] + pbox["height"]/2, steps=10)
            await page.mouse.click(pbox["x"] + pbox["width"]/2, pbox["y"] + pbox["height"]/2)
            await page.wait_for_timeout(1500)
            await page.screenshot(path="after_pricing_click.png")
            print("Saved after_pricing_click.png")
            
        await browser.close()

asyncio.run(test_real_clicks())
