import re
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Any, Optional

IGNORE_PATTERNS = [
    r"login", r"signin", r"signup", r"register", r"auth",
    r"terms", r"privacy", r"legal", r"cookie", r"status",
    r"rss", r"\.xml$", r"\.pdf$", r"wp-admin", r"cart", r"checkout"
]

HIGH_VALUE_PATTERNS = {
    "pricing": [r"pricing", r"plans", r"cost"],
    "features": [r"features", r"product", r"platform", r"capabilities", r"overview"],
    "demo": [r"demo", r"tour", r"interactive", r"sandbox"],
    "about": [r"about", r"company", r"story"]
}

def is_valid_internal_link(base_url: str, target_url: str) -> bool:
    try:
        base_netloc = urlparse(base_url).netloc.lower().replace("www.", "")
        target_parsed = urlparse(target_url)
        target_netloc = target_parsed.netloc.lower().replace("www.", "")
        
        if target_netloc and target_netloc != base_netloc:
            return False
            
        target_path = target_parsed.path.lower()
        for pattern in IGNORE_PATTERNS:
            if re.search(pattern, target_path):
                return False
                
        return True
    except Exception:
        return False

def categorize_link(url: str, anchor_text: str = "") -> str:
    combined = f"{url.lower()} {anchor_text.lower()}"
    for category, patterns in HIGH_VALUE_PATTERNS.items():
        for p in patterns:
            if re.search(p, combined):
                return category
    return "general"

def score_link(url: str, anchor_text: str = "") -> int:
    category = categorize_link(url, anchor_text)
    scores = {
        "features": 10,
        "pricing": 9,
        "demo": 8,
        "about": 6,
        "general": 2
    }
    return scores.get(category, 1)
