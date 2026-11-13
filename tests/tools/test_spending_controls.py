"""Offline spending invariants through real wrappers and mocked transports."""
from __future__ import annotations

import asyncio
import builtins
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib import spending
from lib.spending import Ledger, SpendingError
from tools.base_tool import BaseTool, ToolResult, ToolRuntime
from tools.cost_tracker import ApprovalRequiredError, BudgetExceededError
from tools.provider_pricing import PriceQuoteRequired

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.spending_controls


class FakePaid(BaseTool):
    name = "mock_paid"
    provider = "mock_provider"
    runtime = ToolRuntime.API
    estimate = 0.4

    def __init__(self):
        self.provider_call = MagicMock(return_value=ToolResult(success=True, cost_usd=0.4))

    def estimate_cost(self, inputs):
        return self.estimate

    def execute(self, inputs):
        return self.provider_call(inputs)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(spending, "ROOT", tmp_path)
    monkeypatch.delenv("OPENMONTAGE_ASSET_CACHE", raising=False)
    (tmp_path / "config.yaml").write_text(
        "budget:\n  mode: cap\n  total_usd: 2\n  max_action_usd: 1\n  reserve_pct: 0\n")
    ledger = Ledger()
    ledger.initialize(opening_spend_usd=0, evidence="mock account reviewed; no prior liabilities")
    return ledger


def approved(ledger, tool, inputs=None, **kwargs):
    quote = ledger.quote(tool, inputs or {}, **kwargs)
    ledger.approve(quote["id"], evidence="test human approved this exact quote")
    return quote["id"]


def limits(ledger, total=2, maximum=1, reserve=0, mode="cap"):
    (ledger.root / "config.yaml").write_text(
        f"budget:\n  mode: {mode}\n  total_usd: {total}\n  max_action_usd: {maximum}\n  reserve_pct: {reserve}\n")


def test_no_approval_blocks_provider_and_shows_estimate(ledger):
    tool = FakePaid()
    with pytest.raises(ApprovalRequiredError, match='"estimated_usd":0.4'):
        tool.execute({})
    tool.provider_call.assert_not_called()
    assert ledger.status()["accounted_usd"] == 0


def test_explicit_single_use_approval_and_conservative_charge(ledger):
    tool = FakePaid()
    token = approved(ledger, tool, ceiling_usd=0.6)
    assert tool.execute({"_spending_approval": token}).success
    assert ledger.status()["accounted_usd"] == 0.6
    assert ledger.show(token)["reported"] == 400000
    with pytest.raises(ApprovalRequiredError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_called_once_with({})


@pytest.mark.parametrize("change", [{"prompt": "changed"}, {"model": "other"},
    {"provider_params": {"n": 50}}, {"output_path": "elsewhere.mp4"}, {"dry_run": True}])
def test_request_mutations_invalidate_approval(ledger, change):
    tool = FakePaid(); token = approved(ledger, tool)
    with pytest.raises(ApprovalRequiredError, match="changed"):
        tool.execute({**change, "_spending_approval": token})
    tool.provider_call.assert_not_called()


def test_changed_input_bytes_invalidate_approval(ledger, tmp_path):
    file = tmp_path / "input.png"; file.write_bytes(b"before")
    tool = FakePaid(); inputs = {"image_path": str(file)}
    token = approved(ledger, tool, inputs)
    file.write_bytes(b"after")
    with pytest.raises(ApprovalRequiredError):
        tool.execute({**inputs, "_spending_approval": token})
    tool.provider_call.assert_not_called()


def test_changed_provider_environment_invalidates(ledger, monkeypatch):
    tool = FakePaid(); token = approved(ledger, tool)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://different.invalid")
    with pytest.raises(ApprovalRequiredError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


def test_expired_approval_blocks(ledger, monkeypatch):
    tool = FakePaid(); token = approved(ledger, tool)
    now = spending.time.time()
    monkeypatch.setattr(spending.time, "time", lambda: now + 901)
    with pytest.raises(ApprovalRequiredError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


@pytest.mark.parametrize("estimate", [None, 0, float("nan"), float("inf"), -1, True, False, "nonsense"])
def test_unknown_or_invalid_price_is_never_free(ledger, estimate):
    tool = FakePaid(); tool.estimate = estimate
    with pytest.raises((SpendingError, PriceQuoteRequired)):
        tool.execute({})
    tool.provider_call.assert_not_called()


def test_estimator_exception_blocks_even_with_manual_quote(ledger, monkeypatch):
    tool = FakePaid()
    def broken(_):
        raise RuntimeError("pricing unavailable")
    monkeypatch.setattr(tool, "estimate_cost", broken)
    with pytest.raises(SpendingError, match="estimator failed"):
        ledger.quote(tool, {}, quoted_usd=1, evidence="not allowed to mask an exception")
    tool.provider_call.assert_not_called()


def test_quote_required_accepts_only_explicit_provider_quote(ledger, monkeypatch):
    tool = FakePaid()
    def unquoted(_):
        raise PriceQuoteRequired("account-specific price")
    monkeypatch.setattr(tool, "estimate_cost", unquoted)
    with pytest.raises(PriceQuoteRequired):
        ledger.quote(tool, {})
    token = approved(ledger, tool, quoted_usd=0.5, ceiling_usd=0.6,
                     evidence="mock vendor quote Q42, exact request, USD maximum")
    assert tool.execute({"_spending_approval": token}).success
    assert ledger.status()["accounted_usd"] == 0.6


@pytest.mark.parametrize("new_price", [0.7, None, 0])
def test_price_drift_requires_new_approval(ledger, new_price):
    tool = FakePaid(); token = approved(ledger, tool)
    tool.estimate = new_price
    with pytest.raises((ApprovalRequiredError, PriceQuoteRequired)):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


@pytest.mark.parametrize("total,maximum,reserve", [(0, 1, 0), (2, 0, 0), (0.5, 1, 0.5)])
def test_cap_refusal_before_provider(ledger, total, maximum, reserve):
    tool = FakePaid(); token = approved(ledger, tool)
    limits(ledger, total, maximum, reserve)
    with pytest.raises(BudgetExceededError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()
    assert ledger.show(token)["state"] == "approved"


@pytest.mark.parametrize("bad", [".nan", ".inf", "-1", "true", "null", "garbage"])
def test_invalid_config_blocks(ledger, bad):
    tool = FakePaid(); token = approved(ledger, tool)
    limits(ledger, total=bad)
    with pytest.raises(SpendingError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


@pytest.mark.parametrize("mode", ["warn", "observe", "disabled"])
def test_weaker_modes_do_not_disable_cap(ledger, mode):
    tool = FakePaid(); token = approved(ledger, tool)
    limits(ledger, mode=mode)
    with pytest.raises(SpendingError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


def test_environment_disable_and_wildcard_are_ignored(ledger, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_BUDGET_DISABLED", "1")
    monkeypatch.setenv("OPENMONTAGE_APPROVE_TOOLS", "*")
    monkeypatch.setenv("OPENMONTAGE_BUDGET_MODE", "observe")
    tool = FakePaid()
    with pytest.raises(ApprovalRequiredError):
        tool.execute({"approved": True})
    tool.provider_call.assert_not_called()


@pytest.mark.parametrize("damage", ["missing", "corrupt", "identity", "missing_config"])
def test_unavailable_ledger_or_policy_fails_closed(ledger, damage):
    tool = FakePaid(); token = approved(ledger, tool)
    if damage == "missing": ledger.path.unlink()
    elif damage == "corrupt": ledger.path.write_bytes(b"not sqlite")
    elif damage == "identity": (ledger.directory / "identity").write_text("wrong")
    else: (ledger.root / "config.yaml").unlink()
    with pytest.raises(SpendingError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()


def test_missing_ledger_never_auto_initializes(ledger):
    ledger.path.unlink()
    with pytest.raises(SpendingError):
        FakePaid().execute({})
    assert not ledger.path.exists()
    with pytest.raises(FileExistsError):
        ledger.initialize(opening_spend_usd=0, evidence="attempted reset")


def test_reservation_write_failure_prevents_provider(ledger):
    tool = FakePaid(); token = approved(ledger, tool)
    with sqlite3.connect(ledger.path) as db:
        db.execute("CREATE TRIGGER reject_reserve BEFORE UPDATE ON requests "
                   "BEGIN SELECT RAISE(ABORT, 'disk unavailable'); END")
    with pytest.raises(SpendingError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_not_called()
    assert ledger.show(token)["state"] == "approved"


@pytest.mark.parametrize("failure", [RuntimeError("timeout after acceptance"), KeyboardInterrupt(), SystemExit()])
def test_exceptions_and_cancellation_retain_money_and_consume_approval(ledger, failure):
    tool = FakePaid(); tool.provider_call.side_effect = failure
    token = approved(ledger, tool)
    with pytest.raises(type(failure)):
        tool.execute({"_spending_approval": token})
    assert ledger.show(token)["state"] == "unresolved"
    assert ledger.status()["accounted_usd"] == 0.4
    with pytest.raises(ApprovalRequiredError):
        tool.execute({"_spending_approval": token})
    tool.provider_call.assert_called_once()


@pytest.mark.parametrize("result", [ToolResult(False), ToolResult(True, cost_usd=None),
    ToolResult(True), ToolResult(False, cost_usd=0.3), ToolResult(True, cost_usd=float("nan"))])
def test_unknown_or_failed_results_never_refund(ledger, result):
    tool = FakePaid(); tool.provider_call.return_value = result
    token = approved(ledger, tool)
    with pytest.raises(SpendingError, match="unresolved"):
        tool.execute({"_spending_approval": token})
    assert ledger.status()["accounted_usd"] == 0.4
    new = ledger.quote(tool, {"prompt": "different"})["id"]
    with pytest.raises(SpendingError, match="Unresolved"):
        ledger.approve(new, evidence="new request still cannot bypass unresolved billing")


def test_overrun_records_actual_and_stops_follow_on_calls(ledger):
    tool = FakePaid(); tool.provider_call.return_value = ToolResult(True, cost_usd=1.2)
    token = approved(ledger, tool)
    with pytest.raises(SpendingError, match="overrun"):
        tool.execute({"_spending_approval": token})
    assert ledger.status()["accounted_usd"] == 1.2


def test_reconciliation_requires_evidence_and_does_not_reuse_token(ledger):
    tool = FakePaid(); token = approved(ledger, tool)
    tool.provider_call.side_effect = RuntimeError("transport lost")
    with pytest.raises(RuntimeError): tool.execute({"_spending_approval": token})
    with pytest.raises(SpendingError): ledger.reconcile(token, actual_usd=0, evidence="")
    ledger.reconcile(token, actual_usd=0, evidence="mock vendor confirmed no job accepted, receipt 17")
    assert ledger.status()["accounted_usd"] == 0
    with pytest.raises(ApprovalRequiredError): tool.execute({"_spending_approval": token})
    assert tool.provider_call.call_count == 1


def test_success_with_lower_report_does_not_free_approved_maximum(ledger):
    tool = FakePaid(); token = approved(ledger, tool, ceiling_usd=0.9)
    tool.execute({"_spending_approval": token})
    assert ledger.status()["accounted_usd"] == 0.9
    ledger.reconcile(token, actual_usd=0.4, evidence="mock paid invoice for exactly 0.4 USD")
    assert ledger.status()["accounted_usd"] == 0.4


def test_concurrent_calls_cannot_oversubscribe(ledger):
    tool = FakePaid()
    tokens = [approved(ledger, tool, {"i": i}) for i in range(4)]
    limits(ledger, total=0.5)
    def run(i):
        try:
            tool.execute({"i": i, "_spending_approval": tokens[i]})
            return "sent"
        except BudgetExceededError:
            return "blocked"
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(run, range(4)))
    assert outcomes.count("sent") == 1
    assert tool.provider_call.call_count == 1
    assert ledger.status()["accounted_usd"] == 0.4


def test_parallel_use_of_same_token_submits_only_once(ledger):
    tool = FakePaid(); token = approved(ledger, tool)
    def run(_):
        try: return tool.execute({"_spending_approval": token}).success
        except ApprovalRequiredError: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(run, range(4))) == 1
    tool.provider_call.assert_called_once()


def test_hard_process_exit_retains_reservation(ledger):
    # A real child dies inside a mock provider, bypassing all finally handlers.
    script = '''
import os, sys
from lib import spending
from tools.base_tool import BaseTool, ToolRuntime
spending.ROOT = __import__('pathlib').Path(sys.argv[1])
class CrashTool(BaseTool):
    name = 'crash'; runtime = ToolRuntime.API
    def estimate_cost(self, inputs): return 0.4
    def execute(self, inputs): os._exit(73)
t = CrashTool(); ledger = spending.Ledger()
q = ledger.quote(t, {})
ledger.approve(q['id'], evidence='mock child authorized')
print(q['id'], flush=True)
t.execute({'_spending_approval': q['id']})
'''
    file = ledger.root / "crash.py"; file.write_text(script)
    child = subprocess.run([sys.executable, str(file), str(ledger.root)], cwd=REPO,
                           env={**os.environ, "PYTHONPATH": str(REPO)}, capture_output=True, text=True)
    assert child.returncode == 73, child.stderr
    token = child.stdout.strip()
    assert Ledger(ledger.root).show(token)["state"] == "reserved"
    assert Ledger(ledger.root).status()["accounted_usd"] == 0.4
    limits(ledger, total=0.5)
    new = ledger.quote(FakePaid(), {})["id"]
    with pytest.raises(BudgetExceededError): ledger.approve(new, evidence="cannot ignore crash liability")


def test_event_import_failure_cannot_skip_governance(ledger, monkeypatch):
    original = builtins.__import__
    def broken(name, *args, **kwargs):
        if name == "lib.events": raise ImportError("optional events unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", broken)
    tool = FakePaid()
    with pytest.raises(ApprovalRequiredError): tool.execute({})
    tool.provider_call.assert_not_called()


def test_local_tools_work_without_policy_or_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(spending, "ROOT", tmp_path)
    class Local(BaseTool):
        name = "local"
        def execute(self, inputs): return ToolResult(True)
    assert Local().execute({}).success
    assert not (tmp_path / ".openmontage-spending").exists()


def test_real_tts_selector_passes_approval_to_provider_once(ledger, monkeypatch):
    from tools.audio.tts_selector import TTSSelector
    selector = TTSSelector(); tool = FakePaid(); inputs = {"text": "mock narration"}
    monkeypatch.setattr(selector, "_providers", lambda: [tool])
    monkeypatch.setattr(selector, "_select_best_tool", lambda *a: (tool, None))
    monkeypatch.setattr(selector, "_tool_context_payload", lambda *a: {})
    with pytest.raises(ApprovalRequiredError): selector.execute(inputs)
    token = approved(ledger, tool, inputs)
    assert selector.execute({**inputs, "_spending_approval": token}).success
    tool.provider_call.assert_called_once()
    assert ledger.status()["accounted_usd"] == 0.4


def test_real_hybrid_image_cloud_is_gated_local_is_free(ledger, monkeypatch):
    from tools.graphics.image_gen import ImageGen
    tool = ImageGen()
    remote = MagicMock(); monkeypatch.setattr(tool, "_generate_openai", remote)
    with pytest.raises(ApprovalRequiredError): tool.execute({"provider": "openai", "prompt": "test"})
    remote.assert_not_called()
    monkeypatch.setattr(tool, "_generate_local", lambda _: ToolResult(True))
    assert tool.execute({"provider": "local", "prompt": "test"}).success


def test_remote_comfyui_cannot_claim_local_free(ledger):
    from tools.graphics.comfyui_image import ComfyUIImage
    tool = ComfyUIImage(); tool._client.server_url = "https://rented-gpu.invalid"
    assert spending.requires_gate(tool, {})
    with pytest.raises((SpendingError, PriceQuoteRequired)):
        tool.execute({"prompt": "test"})
    tool._client.server_url = "http://127.0.0.1:8188"
    assert not spending.requires_gate(tool, {})


def test_real_openai_transport_approval_and_no_automatic_sdk_retry(ledger, monkeypatch, tmp_path):
    from tools.audio.openai_tts import OpenAITTS
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    client = MagicMock(); constructor = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=constructor))
    monkeypatch.setattr("tools.analysis.audio_probe.probe_duration", lambda _: 1.0)
    tool = OpenAITTS(); inputs = {"text": "Mocked narration only", "output_path": str(tmp_path / "mock.wav")}
    with pytest.raises(ApprovalRequiredError): tool.execute(inputs)
    constructor.assert_not_called()
    token = approved(ledger, tool, inputs)
    assert tool.execute({**inputs, "_spending_approval": token}).success
    constructor.assert_called_once_with(max_retries=0)
    client.audio.speech.with_streaming_response.create.assert_called_once()


def test_registry_fleet_all_paid_api_tools_block_before_execute(ledger, monkeypatch):
    from tools.tool_registry import ToolRegistry
    registry = ToolRegistry(); registry.discover()
    checked = []
    for tool in registry._tools.values():
        if tool.runtime != ToolRuntime.API or not spending.requires_gate(tool, {}): continue
        # Supply a known quote to isolate the enforcement point across inherited
        # FalMedia, SchemaMedia, SpeechAPI, MiniCut and standalone implementations.
        monkeypatch.setattr(tool, "estimate_cost", lambda _: 0.25)
        with pytest.raises(ApprovalRequiredError): tool.execute({})
        checked.append(tool.name)
    assert len(checked) == 89


@pytest.mark.parametrize("which", ["atlas", "jobs", "kling", "minicut", "heygen", "modal"])
def test_shared_submission_helpers_block_direct_calls(which):
    with pytest.raises(SpendingError):
        if which == "atlas":
            from tools.atlas_client import submit
            submit("https://mock.invalid", {}, "fake")
        elif which == "jobs":
            from tools.provider_jobs import request_json
            request_json("POST", "https://mock.invalid")
        elif which == "kling":
            from tools._kling.client import KlingClient
            KlingClient(api_key="fake").post("/mock", {})
        elif which == "minicut":
            from tools.minicut_cli import run
            run(["gen", "mock", "--yes"])
        else:
            from tools.video import _shared
            getattr(_shared, "generate_" + ("heygen_video" if which == "heygen" else "ltx_modal_video"))({})


def test_cli_rejects_noninteractive_approval(monkeypatch):
    from lib.spending_cli import confirm
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SpendingError): confirm("APPROVE quote 1 USD")


def test_direct_provider_generate_method_is_blocked_before_sdk():
    from tools.audio.openai_tts import OpenAITTS
    with pytest.raises(SpendingError): OpenAITTS()._generate({"text": "do not send"})
    from tools.audio.heygen_tts import HeyGenTTS
    with pytest.raises(SpendingError): HeyGenTTS().generate({}, "fake")


def test_recursive_paid_execute_cannot_reuse_active_approval(ledger):
    class Recursive(FakePaid):
        def execute(self, inputs):
            return self.execute(inputs)
    tool = Recursive(); token = approved(ledger, tool)
    with pytest.raises(ApprovalRequiredError): tool.execute({"_spending_approval": token})
    assert ledger.show(token)["state"] == "unresolved"


def test_standalone_lyria_blocked_before_sdk_import():
    file = REPO / ".agents/skills/hyperframes-media/scripts/lyria-recipe.py"
    spec = importlib.util.spec_from_file_location("lyria_recipe", file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="blocked"):
        asyncio.run(module.generate_bgm(SimpleNamespace()))


def test_standalone_js_paid_calls_block_without_fetch(tmp_path):
    scripts = REPO / ".agents/skills/hyperframes-media/scripts/lib"
    program = f'''
import {{ synthesizeOne }} from {json.dumps((scripts / 'tts.mjs').as_uri())};
import {{ heygenJSON }} from {json.dumps((scripts / 'heygen.mjs').as_uri())};
import {{ generateBgmDetached }} from {json.dumps((scripts / 'bgm.mjs').as_uri())};
globalThis.fetch = () => {{ throw new Error('NETWORK MUST NOT RUN'); }};
for (const provider of ['heygen','elevenlabs']) {{
  try {{ await synthesizeOne({{provider}}); throw new Error('not blocked'); }}
  catch(e) {{ if (!e.message.includes('blocked')) throw e; }}
}}
try {{ await heygenJSON('/voices/speech', {{method:'POST'}}); throw new Error('not blocked'); }}
catch(e) {{ if (!e.message.includes('blocked')) throw e; }}
process.env.GOOGLE_API_KEY = 'fake';
try {{ generateBgmDetached({{durationS:1,hyperframesDir:{json.dumps(str(tmp_path))},
lyriaRecipe:{json.dumps(str(scripts.parent / 'lyria-recipe.py'))}}}); throw new Error('not blocked'); }}
catch(e) {{ if (!e.message.includes('blocked')) throw e; }}
console.log('blocked without network');
'''
    run = subprocess.run(["node", "--input-type=module", "-e", program], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "blocked without network" in run.stdout
