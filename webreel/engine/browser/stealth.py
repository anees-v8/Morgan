from typing import Dict, Any

STEALTH_SCRIPTS = """
// Mask navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Mock plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Mock languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Mock chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};
"""

COMMON_COOKIE_SELECTORS = [
    "button:has-text('Accept')",
    "button:has-text('Accept all')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Allow all')",
    "button:has-text('I agree')",
    "#onetrust-accept-btn-handler",
    ".cookie-banner button",
    "[aria-label='Accept cookies']"
]

def get_stealth_headers() -> Dict[str, str]:
    # Never override context-level headers in Playwright, as they attach to every subresource
    # (scripts, stylesheets, fonts) and trigger fatal CORS preflight blocks on CDNs like Cloudflare.
    return {}
