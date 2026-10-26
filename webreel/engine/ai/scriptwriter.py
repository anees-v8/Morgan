import json
from typing import List, Dict, Any, Tuple
from ..config import config

class ScriptWriter:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.gemini_api_key

    def extract_feature_cards(self, brand: Dict[str, str], scenes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Extracts 3 high-impact benefit cards for the right sidebar:
        - Card 1: Highlighting features
        - Card 2: Importants (Key metric / core differentiator)
        - Card 3: Other benefits (Trust / scale / ease of onboarding)
        """
        company = brand.get("company_name", "Our Platform")
        domain = brand.get("clean_domain", "example.com").lower()
        tagline = brand.get("tagline", "")
        meta = ""
        for s in scenes:
            if s.get("meta_description"):
                meta += " " + s.get("meta_description")

        meta = meta.strip()

        # Domain-tailored presets for world-class demo fidelity
        if "campusweb" in domain:
            return [
                {
                    "category": "HIGHLIGHTING FEATURES",
                    "title": "1-Tap Dynamic QR Attendance",
                    "desc": "Eliminate paper registers. Instant WhatsApp alerts delivered directly to parents."
                },
                {
                    "category": "IMPORTANTS",
                    "title": "Automated WhatsApp Receipts",
                    "desc": "Collect tuition fees with instant payment links and automated GST-ready invoices."
                },
                {
                    "category": "OTHER BENEFITS",
                    "title": "Zero Commission Guarantee",
                    "desc": "100% direct bank deposits with bank-grade security and zero paperwork."
                }
            ]
        elif "linear" in domain:
            return [
                {
                    "category": "HIGHLIGHTING FEATURES",
                    "title": "Lightning Issue Tracking",
                    "desc": "Built for speed. Keyboard-first navigation and real-time multiplayer sync."
                },
                {
                    "category": "IMPORTANTS",
                    "title": "Automated Cycle Planning",
                    "desc": "Continuous team momentum. Automatic triage and zero project busywork."
                },
                {
                    "category": "OTHER BENEFITS",
                    "title": "Enterprise Git Sync",
                    "desc": "Seamless bi-directional GitHub integration with enterprise-grade privacy."
                }
            ]
        elif "stripe" in domain:
            return [
                {
                    "category": "HIGHLIGHTING FEATURES",
                    "title": "Global Payment Elements",
                    "desc": "Accept 135+ currencies and local payment methods with unified drop-in UI."
                },
                {
                    "category": "IMPORTANTS",
                    "title": "Smart Radar Fraud Defense",
                    "desc": "Machine learning defense that stops fraud while maximizing checkout conversion."
                },
                {
                    "category": "OTHER BENEFITS",
                    "title": "99.999% Uptime Reliability",
                    "desc": "Enterprise financial infrastructure engineered for massive global scale."
                }
            ]

        # Dynamic heuristic generation for any website
        c1_title = "Modern Intelligent Architecture"
        c1_desc = f"Engineered specifically for {company} workflows with lightning-fast responsiveness."
        if len(tagline) > 15:
            c1_title = tagline.split(".")[0].split("—")[0].strip()[:32]
            c1_desc = f"Experience {company}'s purpose-built platform designed for speed and reliability."

        c2_title = "Automated Workflows & Control"
        c2_desc = "Eliminate manual repetitive tasks with unified dashboard control and real-time updates."
        if "fee" in meta.lower() or "pay" in meta.lower():
            c2_title = "Seamless Financial Automation"
            c2_desc = "Automate payment flows, receipts, and accounts with complete data accuracy."
        elif "ai" in meta.lower() or "agent" in meta.lower():
            c2_title = "Autonomous AI Intelligence"
            c2_desc = "Leverage native generative intelligence to accelerate execution and productivity."

        c3_title = "Bank-Grade Security & Scale"
        c3_desc = f"Enterprise data privacy, zero friction onboarding, and 24/7 dedicated support."

        return [
            {"category": "HIGHLIGHTING FEATURES", "title": c1_title, "desc": c1_desc},
            {"category": "IMPORTANTS", "title": c2_title, "desc": c2_desc},
            {"category": "OTHER BENEFITS", "title": c3_title, "desc": c3_desc}
        ]

    def generate_script(
        self,
        brand: Dict[str, str],
        scenes: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        """
        Generates timed narration lines mapped 1:1 to each visual scene,
        along with the 3 right-hand sidebar feature cards.
        """
        company = brand.get("company_name", "Our Platform")
        domain = brand.get("clean_domain", "example.com")
        tagline = brand.get("tagline", "The modern digital experience")

        # Dynamic story: narration + cards come from the plan written for THIS website
        # (see ai/story_director.py). The fixed templates below remain the fallback.
        site_plan = next((s.get("site_plan") for s in scenes if s.get("site_plan")), None)
        if site_plan and site_plan.get("cards"):
            cards = [{"category": c["category"], "title": c["title"], "desc": c["desc"]} for c in site_plan["cards"][:3]]
        else:
            cards = self.extract_feature_cards(brand, scenes)

        # High-Impact Storytelling Framework (Hook -> Solution -> Core Pillars -> Proof/CTA)
        for idx, s in enumerate(scenes):
            stype = s.get("scene_type", "features").lower()
            stitle = s.get("title", "").split("|")[0].split("—")[0].strip() or "Core Platform"

            if s.get("plan_say"):
                s["narration"] = s["plan_say"]
                s["duration_sec"] = round(len(s["narration"].split()) / 2.4 + 0.6)
                s["active_card_idx"] = int(s.get("plan_card", min(idx, 2)))
                continue

            if idx == 0 or stype == "hero":
                # Hook & Radical Solution introduction
                clean_tag = tagline if len(tagline) > 10 else f"the purpose-built platform for modern teams"
                s["narration"] = f"Meet {company}. {clean_tag}. Built from the ground up to eliminate daily busywork and deliver unmatched speed, scale, and operational control."
                s["duration_sec"] = 11
                s["active_card_idx"] = 0
            elif stype == "dashboard":
                # Pillar 1: Central Operations & Visibility
                card_ref = cards[0]["title"]
                s["narration"] = f"Inside the core dashboard, everything is unified. From {card_ref.lower()} to automated tracking, manage your entire operations effortlessly from a single screen."
                s["duration_sec"] = 10
                s["active_card_idx"] = 0
            elif stype == "features":
                # Pillar 2: Automation & Team Workflows
                card_ref = cards[1]["title"]
                s["narration"] = f"Engineered for high performance. Experience {card_ref.lower()}, instant synchronization, and workflows that keep your entire organization moving forward without friction."
                s["duration_sec"] = 10
                s["active_card_idx"] = 1
            elif stype == "pricing":
                # Proof & Unstoppable Value Proposition
                card_ref = cards[2]["title"]
                s["narration"] = f"Transparent, flexible plans backed by our {card_ref.lower()}. Zero paperwork, zero hidden friction. Take your operations to the next level today at {domain}."
                s["duration_sec"] = 10
                s["active_card_idx"] = 2
            else:
                s["narration"] = f"Designed for modern excellence. Transform your daily productivity and scale with confidence on {company}."
                s["duration_sec"] = 9
                s["active_card_idx"] = 1

        return scenes, cards
