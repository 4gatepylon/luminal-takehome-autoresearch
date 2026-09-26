"""Implemented by Codex (GPT-6).

Quota policy and the real SDK transport against a local scripted app server.
"""

import os
from pathlib import Path
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from openai_codex import CodexConfig
from openai_codex.async_client import AsyncCodexClient
from openai_codex.generated.v2_all import GetAccountRateLimitsResponse

from autoresearch.config import load_config
from autoresearch.usage import UsageUnavailable, read_usage, usage_stop_reason


def response(primary=0, secondary=0, *, primary_minutes=300, secondary_minutes=10080, **extra):
    return GetAccountRateLimitsResponse.model_validate(
        {
            "rateLimits": {
                "primary": {"usedPercent": primary, "windowDurationMins": primary_minutes},
                "secondary": {"usedPercent": secondary, "windowDurationMins": secondary_minutes},
            },
            **extra,
        }
    )


class UsagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_exact_minimums_are_allowed_and_either_window_can_stop(self):
        self.assertIsNone(usage_stop_reason(response(95, 75), self.config))
        self.assertIn("5h: 4% remaining", usage_stop_reason(response(96, 0), self.config))
        self.assertIn("weekly: 24% remaining", usage_stop_reason(response(0, 76), self.config))

    def test_duration_not_position_selects_threshold_and_overrides_apply(self):
        usage = response(76, 0, primary_minutes=10080, secondary_minutes=300)
        self.assertIn("weekly", usage_stop_reason(usage, self.config))
        config = load_config(overrides={"min_weekly_limit_remaining_allowed": 20})
        self.assertIsNone(usage_stop_reason(usage, config))
        config = load_config(overrides={"min_5h_limit_remaining_allowed": 15})
        self.assertIn("minimum 15%", usage_stop_reason(response(90, 0), config))

    def test_unknown_durations_are_explicitly_unsupported(self):
        for minutes in (60, 1440, 43200, None):
            with self.subTest(minutes=minutes):
                usage = response(76, 0, primary_minutes=minutes)
                with self.assertRaisesRegex(UsageUnavailable, "unsupported quota window"):
                    usage_stop_reason(usage, self.config)

    def test_complete_multi_bucket_view_takes_precedence_and_checks_every_bucket(self):
        buckets = {
            "codex": {"primary": {"usedPercent": 10, "windowDurationMins": 300}},
            "another": {"secondary": {"usedPercent": 76, "windowDurationMins": 10080}},
        }
        usage = response(100, 100, rateLimitsByLimitId=buckets)
        self.assertIn("another weekly: 24%", usage_stop_reason(usage, self.config))
        buckets["another"]["secondary"]["usedPercent"] = 75
        self.assertIsNone(usage_stop_reason(response(100, 100, rateLimitsByLimitId=buckets), self.config))

    def test_monthly_credit_limit_has_its_own_minimum(self):
        for remaining, expected in ((24, "monthly credit limit"), (25, None)):
            with self.subTest(remaining=remaining):
                usage = GetAccountRateLimitsResponse.model_validate(
                    {"rateLimits": {"individualLimit": {"remainingPercent": remaining, "limit": "100", "used": "75", "resetsAt": 123}}}
                )
                reason = usage_stop_reason(usage, self.config)
                if expected:
                    self.assertIn(expected, reason)
                else:
                    self.assertIsNone(reason)
                config = load_config(overrides={"min_monthly_limit_remaining_allowed": 20})
                self.assertIsNone(usage_stop_reason(usage, config))

    def test_server_block_and_exhaustion_stop_even_with_zero_minimum(self):
        config = load_config(overrides={"min_weekly_limit_remaining_allowed": 0, "min_5h_limit_remaining_allowed": 0})
        self.assertIsNotNone(usage_stop_reason(response(0, 0, ordinaryUsageAllowed=False), config))
        for field, value in (("spendControlReached", True), ("rateLimitReachedType", "workspace_owner_credits_depleted")):
            with self.subTest(field=field):
                usage = GetAccountRateLimitsResponse.model_validate({"rateLimits": {field: value}})
                self.assertIsNotNone(usage_stop_reason(usage, config))
        for used in (100, 105):
            with self.subTest(used=used):
                self.assertIn("0% remaining", usage_stop_reason(response(used, 0), config))

    def test_empty_and_malformed_quotas_are_unknown(self):
        for raw in (
            {"rateLimits": {}},
            {"rateLimits": {"primary": {"usedPercent": -1}}},
            {"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": 0}}},
            {"rateLimits": {}, "rateLimitsByLimitId": {"codex": {"primary": {}}}},
            {"rateLimits": {}, "rateLimitsByLimitId": {"codex": None}},
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(UsageUnavailable):
                    usage_stop_reason(GetAccountRateLimitsResponse.model_validate(raw), self.config)

    def test_null_optional_window_is_supported(self):
        usage = GetAccountRateLimitsResponse.model_validate(
            {"rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300}, "secondary": None}}
        )
        self.assertIsNone(usage_stop_reason(usage, self.config))


class UsageTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.server = self.root / "server.py"
        self.server.write_text(
            textwrap.dedent("""\
                import json
                import os
                from pathlib import Path
                import sys
                import time

                root = Path(__file__).parent
                (root / 'pid').write_text(str(os.getpid()))
                scenario = (root / 'scenario').read_text()
                for line in sys.stdin:
                    message = json.loads(line)
                    method = message['method']
                    with (root / 'methods').open('a') as log:
                        log.write(method + '\\n')
                    if 'id' not in message:
                        continue
                    if method == 'initialize':
                        if scenario == 'stall_initialize':
                            time.sleep(30)
                        result = {'userAgent': 'codex-cli/0.157.0'}
                    elif method == 'account/rateLimits/read':
                        if scenario == 'stall_usage':
                            time.sleep(30)
                        if scenario == 'close':
                            break
                        if scenario == 'error':
                            print(json.dumps({'id': message['id'], 'error': {'code': -32603, 'message': 'login required'}}), flush=True)
                            continue
                        result = {} if scenario == 'malformed' else json.loads((root / 'response.json').read_text())
                    else:
                        raise AssertionError('Unexpected method: ' + method)
                    print(json.dumps({'method': 'example/notification', 'params': {}}), flush=True)
                    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
                """)
        )
        (self.root / "response.json").write_text(response(12, 34).model_dump_json(by_alias=True))
        # Replace only the launched command; handshake, parsing, and cleanup are
        # handled by the real official SDK, with no credentials or network access.
        factory_patch = patch(
            "autoresearch.usage.AsyncCodexClient",
            side_effect=lambda config: AsyncCodexClient(CodexConfig(launch_args_override=(sys.executable, "-u", str(self.server)))),
        )
        self.factory = factory_patch.start()
        self.addCleanup(factory_patch.stop)
        which_patch = patch("autoresearch.usage.shutil.which", return_value="/installed/codex")
        which_patch.start()
        self.addCleanup(which_patch.stop)

    def read(self, scenario="success", timeout=2):
        (self.root / "scenario").write_text(scenario)
        try:
            return read_usage(cwd=self.root, timeout=timeout)
        finally:
            pid_path = self.root / "pid"
            if pid_path.exists():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_path.read_text()), 0)

    def test_reads_fresh_quota_with_sdk_handshake_and_no_agent_turn(self):
        usage = self.read()
        self.assertEqual(usage.rate_limits.primary.used_percent, 12)
        self.assertEqual(usage.rate_limits.secondary.used_percent, 34)
        self.assertEqual((self.root / "methods").read_text().splitlines(), ["initialize", "initialized", "account/rateLimits/read"])
        config = self.factory.call_args.args[0]
        self.assertEqual(config.codex_bin, "/installed/codex")
        self.assertEqual(config.cwd, str(self.root))

    def test_authentication_transport_and_schema_errors_stop_the_check(self):
        for scenario in ("error", "close", "malformed"):
            with self.subTest(scenario=scenario), self.assertRaises(UsageUnavailable):
                self.read(scenario)

    def test_timeout_covers_initialization_and_request_and_reaps_process(self):
        for scenario in ("stall_initialize", "stall_usage"):
            start = time.monotonic()
            with self.subTest(scenario=scenario), self.assertRaisesRegex(UsageUnavailable, "timed out"):
                self.read(scenario, timeout=0.2)
            self.assertLess(time.monotonic() - start, 5)

    def test_missing_cli_and_invalid_timeouts_do_not_launch(self):
        with patch("autoresearch.usage.shutil.which", return_value=None), self.assertRaisesRegex(UsageUnavailable, "Install"):
            read_usage()
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                read_usage(timeout=timeout)
        self.factory.assert_not_called()
