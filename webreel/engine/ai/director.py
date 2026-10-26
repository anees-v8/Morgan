import json
import os
from typing import List, Dict, Any
from ..config import config

class DirectorAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.gemini_api_key

    def plan_scenes(self, website_info: Dict[str, Any], candidate_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Directs scene selection and time allocation for a 90-second video.
        """
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                prompt = f"""You are a product demo video director for WebReel.
Given website: {website_info.get('company_name')} ({website_info.get('clean_domain')})
Tagline: {website_info.get('tagline')}
Discovered pages: {json.dumps([p.get('url') for p in candidate_pages])}

Plan the 5 most impactful scenes for a 90-second product demo video.
Return JSON array with objects:
[{{"page_type": "home|features|pricing|demo|about", "focus": "headline or feature", "duration_seconds": 12}}]
"""
                resp = model.generate_content(prompt)
                text = resp.text.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(text)
                if isinstance(parsed, list) and len(parsed) > 0:
                    return parsed
            except Exception as e:
                pass

        # Intelligent Fallback Plan (90s structured template)
        return [
            {"page_type": "home", "focus": "Hero value proposition and core offering", "duration_seconds": 15},
            {"page_type": "features", "focus": "Core capabilities and interactive toolset", "duration_seconds": 25},
            {"page_type": "features", "focus": "Platform workflow and automation", "duration_seconds": 20},
            {"page_type": "pricing", "focus": "Plans, tiers and transparent pricing", "duration_seconds": 15},
            {"page_type": "outro", "focus": "Call to action and domain link", "duration_seconds": 10}
        ]
