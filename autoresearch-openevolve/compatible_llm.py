"""Adapt OpenEvolve 0.3.2's requests for GPT-6 and Fast mode.

The pinned backend lacks GPT-6 parameter handling and service-tier configuration.
Keeping this compatibility shim separate leaves the research runner focused on
evaluation and makes it easy to remove when upstream supports these settings.
"""

import os
from typing import Any

from openevolve.llm.openai import OpenAILLM


class CompatibleLLM(OpenAILLM):
    async def _call_api(self, params: dict[str, Any]) -> str:
        params = params.copy()
        if self.model.rsplit("/", 1)[-1].startswith("gpt-6"):
            params.pop("temperature", None)
            params.pop("top_p", None)
            params["max_completion_tokens"] = params.pop("max_tokens", None)
        for key in ("max_tokens", "max_completion_tokens"):
            if params.get(key) is None:
                params.pop(key, None)
        if tier := os.getenv("OPENAI_SERVICE_TIER"):
            params["service_tier"] = tier
        return await super()._call_api(params)
