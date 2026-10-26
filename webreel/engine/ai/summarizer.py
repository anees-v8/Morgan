import os
import re
from urllib.parse import urlparse
from typing import Dict, Any

def extract_brand_summary(domain_or_url: str, title: str = "", meta_desc: str = "") -> Dict[str, str]:
    parsed = urlparse(domain_or_url)
    hostname = parsed.netloc if parsed.netloc else parsed.path
    clean_domain = hostname.lower().replace("www.", "").split(":")[0]
    
    # Extract clean company name
    raw_name = clean_domain.split(".")[0]
    company_name = raw_name.replace("-", " ").replace("_", " ").title()
    
    # Extract tagline
    tagline = meta_desc.strip()
    if not tagline and title:
        # Check if title has separator like "Stripe | Financial Infrastructure for the Web"
        for sep in ["|", "—", "-", ":", "•"]:
            if sep in title:
                parts = title.split(sep)
                if len(parts) > 1:
                    tagline = parts[1].strip()
                    break
    if not tagline:
        tagline = f"The modern platform for {company_name}"

    # Truncate tagline if too long
    if len(tagline) > 110:
        tagline = tagline[:107] + "..."

    return {
        "company_name": company_name,
        "clean_domain": clean_domain,
        "tagline": tagline,
        "usp": meta_desc or f"Experience the future of {company_name} online."
    }
