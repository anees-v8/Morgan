from typing import Dict, Any
from pathlib import Path
from ..config import config

class VisionAnalyzer:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.gemini_api_key

    def analyze_screenshot(self, image_path: Path, page_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Uses Gemini Vision (or local fallback) to identify page purpose and visual focal points.
        """
        if self.api_key and image_path.exists():
            try:
                import google.generativeai as genai
                from PIL import Image
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                img = Image.open(str(image_path))
                prompt = (
                    "Analyze this webpage screenshot. Return JSON: "
                    '{"headline": "key title", "summary": "1 sentence purpose", "zoom_target": "center|cta|table"}'
                )
                resp = model.generate_content([prompt, img])
                text = resp.text.strip()
                import json
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                return json.loads(text)
            except Exception:
                pass

        # Robust Heuristic Fallback
        title = page_info.get("title", "")
        clean_title = title.split("|")[0].split("—")[0].split("-")[0].strip() or "Feature Overview"
        return {
            "headline": clean_title,
            "summary": page_info.get("meta_description") or f"Explore the capabilities of {clean_title}.",
            "zoom_target": "cta"
        }
