"""Implemented by Codex (GPT-6).

Read account quotas with the official Codex SDK; no agent turn is started.
"""

import asyncio
import math
from pathlib import Path
import shutil

from openai_codex import CodexConfig, CodexError
from openai_codex.async_client import AsyncCodexClient
from openai_codex.generated.v2_all import GetAccountRateLimitsResponse, RateLimitSnapshot
from pydantic import ValidationError

from .config import ResearchConfig


class UsageUnavailable(RuntimeError):
    """The account's remaining quota could not be established."""


def read_usage(*, cwd: Path | None = None, timeout: float = 15) -> GetAccountRateLimitsResponse:
    """Fetch fresh ChatGPT account limits using the runner's installed Codex CLI.

    Reuses Codex authentication without reading credentials ourselves. API-key
    accounts without ChatGPT quotas raise UsageUnavailable. The SDK owns the
    app-server transport, response models, and process cleanup.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Usage timeout must be finite and positive")
    executable = shutil.which("codex")
    if executable is None:
        raise UsageUnavailable("Install the Codex CLI and run codex login before checking usage")

    async def fetch() -> GetAccountRateLimitsResponse:
        config = CodexConfig(codex_bin=executable, cwd=str(cwd) if cwd is not None else None)
        async with AsyncCodexClient(config) as client:

            async def request() -> GetAccountRateLimitsResponse:
                await client.initialize()
                return await client.request("account/rateLimits/read", None, response_model=GetAccountRateLimitsResponse)

            # Closing the SDK on timeout also unblocks its background reader.
            return await asyncio.wait_for(request(), timeout=timeout)

    try:
        return asyncio.run(fetch())
    except asyncio.TimeoutError as exc:
        raise UsageUnavailable(f"Codex usage check timed out after {timeout:g}s") from exc
    except (CodexError, OSError, ValidationError) as exc:
        raise UsageUnavailable(f"Cannot read Codex account usage: {exc}") from exc


def usage_stop_reason(usage: GetAccountRateLimitsResponse, config: ResearchConfig) -> str | None:
    """Return why to stop, or None when every reported limit has enough quota.

    Window durations identify weekly/5h quotas; primary/secondary order is not
    significant. The SDK's individual_limit is the workspace monthly credit limit.
    Exact minimums are allowed, but an exhausted or server-blocked quota stops.
    Missing/malformed quota information raises UsageUnavailable, never means 0% used.
    """
    if usage.ordinary_usage_allowed is False:
        return "Codex reports that included account usage is unavailable"
    # Prefer the complete view; older servers only return the single snapshot.
    try:
        buckets = (
            {key: RateLimitSnapshot.model_validate(value) for key, value in usage.rate_limits_by_limit_id.items()}
            if usage.rate_limits_by_limit_id
            else {usage.rate_limits.limit_id or "codex": usage.rate_limits}
        )
    except ValidationError as exc:
        raise UsageUnavailable(f"Invalid Codex quota snapshot: {exc}") from exc

    observed = False
    for name, bucket in buckets.items():
        if bucket.rate_limit_reached_type is not None:
            return f"{name}: {bucket.rate_limit_reached_type.value}"
        if bucket.spend_control_reached:
            return f"{name}: spend limit reached"
        for window in (bucket.primary, bucket.secondary):
            if window is None:
                continue
            duration = window.window_duration_mins
            if window.used_percent < 0:
                raise UsageUnavailable(f"{name}: invalid Codex quota window")
            if duration == 7 * 24 * 60:
                label, minimum = "weekly", config.min_weekly_limit_remaining_allowed
            elif duration == 5 * 60:
                label, minimum = "5h", config.min_5h_limit_remaining_allowed
            else:
                raise UsageUnavailable(f"{name}: unsupported quota window duration {duration!r} minutes")
            observed = True
            remaining = max(0, 100 - window.used_percent)
            if remaining == 0 or remaining < minimum:
                return f"{name} {label}: {remaining:g}% remaining (minimum {minimum:g}%)"
        if bucket.individual_limit is not None:
            observed = True
            remaining = bucket.individual_limit.remaining_percent
            if not 0 <= remaining <= 100:
                raise UsageUnavailable(f"{name}: invalid remaining monthly credit percentage")
            minimum = config.min_monthly_limit_remaining_allowed
            if remaining == 0 or remaining < minimum:
                return f"{name} monthly credit limit: {remaining:g}% remaining (minimum {minimum:g}%)"
    if not observed:
        raise UsageUnavailable("Codex returned no quota percentages; remaining usage is unknown")
    return None
