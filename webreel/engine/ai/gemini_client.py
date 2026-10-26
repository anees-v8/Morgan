"""
Thin, defensive wrapper around the google-genai SDK for structured (JSON) generation with images.

Built for the *free tier*: a handful of calls per video, but models differ in what the free tier
allows and get retired. So it walks a configurable model chain (GEMINI_MODELS), skipping a model
that is not found / has no free quota, waiting out per-minute rate limits, and finally trying
whatever Flash models the account can actually list.

Auth: GEMINI_API_KEY (AI Studio, free tier)  -or-  GOOGLE_GENAI_USE_VERTEXAI=1 (+ GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, application-default credentials) to spend Google Cloud credits instead.
"""
import json
import logging
import os
import re
import time
from typing import Any, List, Optional, Sequence, Tuple, Union

from ..config import config

logger = logging.getLogger("webreel.gemini")

Part = Union[str, Tuple[bytes, str]]       # text, or (image bytes, mime type)


class GeminiClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.gemini_api_key or os.getenv("GOOGLE_API_KEY", "")
        self.use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
        self.models: List[str] = [m.strip() for m in config.gemini_models.split(",") if m.strip()]
        self.errors: List[str] = []
        self.last_model: Optional[str] = None
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self.use_vertex

    def _get(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            if self.use_vertex:
                self._client = genai.Client(vertexai=True)
            else:
                self._client = genai.Client(api_key=self.api_key, http_options=types.HttpOptions(timeout=45_000))
        return self._client

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _retry_delay(msg: str) -> float:
        m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", msg, re.I)
        return float(m.group(1)) if m else 0.0

    @staticmethod
    def _loads(text: str) -> Any:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        return json.loads(text)

    def _discover_flash_models(self) -> List[str]:
        out: List[str] = []
        try:
            for m in self._get().models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "")
                actions = getattr(m, "supported_actions", None) or []
                if "flash" in name and "generateContent" in actions and "image" not in name and "tts" not in name \
                        and "live" not in name and "preview-" not in name:
                    out.append(name)
        except Exception as e:                    # noqa: BLE001
            self.errors.append(f"model discovery failed: {e!r}")
        out.sort(key=lambda n: ("lite" in n, n), reverse=True)    # newest-looking, non-lite first
        return out[:4]

    # ------------------------------------------------------------------ main API
    def generate_json(self, system: str, parts: Sequence[Part], schema: Any,
                      temperature: float = 0.8, thinking_level: Optional[str] = "low") -> Optional[Any]:
        """Return parsed JSON matching `schema` (a pydantic model class), or None if every model failed."""
        if not self.enabled:
            self.errors.append("no GEMINI_API_KEY configured")
            return None
        from google.genai import types, errors as gerrors

        contents: List[Any] = []
        for p in parts:
            if isinstance(p, str):
                contents.append(types.Part.from_text(text=p))
            else:
                contents.append(types.Part.from_bytes(data=p[0], mime_type=p[1]))
        def make_cfg(level: Optional[str]):
            kw: dict = {}
            if level:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level=level)
            return types.GenerateContentConfig(
                system_instruction=system, temperature=temperature,
                response_mime_type="application/json", response_schema=schema, **kw)

        level = thinking_level
        cfg = make_cfg(level)

        tried_discovery = False
        queue = list(self.models)
        while queue:
            model = queue.pop(0)
            not_found = False
            for attempt in range(3):
                try:
                    resp = self._get().models.generate_content(model=model, contents=contents, config=cfg)
                    data = self._loads(resp.text)
                    self.last_model = model
                    return data
                except gerrors.APIError as e:
                    code = getattr(e, "code", 0) or 0
                    msg = str(e)
                    if re.search(r"API_KEY_INVALID|API key not valid|API key expired", msg, re.I):
                        self.errors.append("API key rejected by Google (check GEMINI_API_KEY)")
                        logger.warning("Gemini API key rejected - skipping the LLM for this run")
                        return None
                    if code == 429:
                        delay = self._retry_delay(msg)
                        daily = ("PerDay" in msg) or ("limit: 0" in msg) or delay > 45
                        self.errors.append(f"{model}: 429 {'(no free quota for this model)' if daily else '(rate limit)'}")
                        if daily or attempt == 2:
                            break
                        time.sleep(min(max(delay, 5.0), 40.0))
                        continue
                    if code == 400 and level and re.search(r"thinking", msg, re.I):
                        level = None                     # this model does not take a thinking level: retry without
                        cfg = make_cfg(None)
                        continue
                    if code in (404, 400) and re.search(r"not found|no longer|not supported|unsupported|deprecated|shut", msg, re.I):
                        self.errors.append(f"{model}: unavailable ({code})")
                        not_found = True
                        break
                    if code >= 500:
                        self.errors.append(f"{model}: server error {code}")
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    self.errors.append(f"{model}: API error {code}: {msg[:160]}")
                    break
                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    self.errors.append(f"{model}: bad JSON ({e!r})")
                    temperature = max(0.3, temperature - 0.3)
                    cfg = make_cfg(level)
                    continue
                except Exception as e:           # noqa: BLE001 - network/SDK problems must never crash a video
                    self.errors.append(f"{model}: {e!r}"[:200])
                    break
            if not queue and not tried_discovery:
                tried_discovery = True
                known = set(self.models)
                queue = [m for m in self._discover_flash_models() if m not in known]
        logger.warning("Gemini unavailable (%s)", "; ".join(self.errors[-6:]))
        return None
