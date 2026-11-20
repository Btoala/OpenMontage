"""Fail-closed, per-request spending authorization. No provider calls here.

This ledger is deliberately separate from the legacy reporting CostTracker.
SQLite transactions serialize approvals/reservations across processes. A crash
never frees money or makes an approval reusable. See docs/spending-controls.md.
"""
from __future__ import annotations

import contextvars
import copy
import functools
import hashlib
import inspect
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from urllib.parse import urlparse

from tools.cost_tracker import ApprovalRequiredError, BudgetExceededError
from tools.provider_pricing import PriceQuoteRequired

ROOT = Path(__file__).resolve().parents[1]
_TOKEN = contextvars.ContextVar("spending_approval", default=None)
_ACTIVE = contextvars.ContextVar("spending_active_tool", default=None)
SCALE = 1_000_000


class SpendingError(RuntimeError):
    """Governance unavailable or billing unresolved: do not submit/retry."""


def money(value, *, positive=False):
    """Integer microdollars; reject bool, negative, NaN, infinity and overflow."""
    if isinstance(value, bool) or value is None:
        raise SpendingError("A finite USD amount is required")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (positive and number <= 0):
            raise ValueError
        amount = int((number * SCALE).to_integral_value(rounding=ROUND_CEILING))
        if amount > 10**15:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise SpendingError("Invalid USD amount") from exc


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def policy(root):
    import yaml
    try:
        config = yaml.safe_load((root / "config.yaml").read_text())
        budget = config["budget"]
        if budget["mode"] != "cap":
            raise SpendingError("Paid execution requires budget.mode: cap")
        total = money(budget["total_usd"])
        maximum = money(budget["max_action_usd"])
        reserve = Decimal(str(budget["reserve_pct"]))
        if not reserve.is_finite() or not 0 <= reserve < 1:
            raise SpendingError("reserve_pct must be finite and in [0, 1)")
        usable = int(Decimal(total) * (1 - reserve))
        return {"total": usable, "maximum": maximum}
    except SpendingError:
        raise
    except Exception as exc:
        raise SpendingError("Cannot read valid spending policy; paid execution blocked") from exc


# These are reviewed exceptions, keyed by module AND name, never by a caller's
# provider='free' or a zero estimate. Future API/hybrid tools default to paid.
_FREE = {
    ("tools.audio.freesound_music", "freesound_music"),
    ("tools.audio.pixabay_music", "pixabay_music"),
    ("tools.graphics.pexels_image", "pexels_image"),
    ("tools.graphics.pixabay_image", "pixabay_image"),
    ("tools.video.pexels_video", "pexels_video"),
    ("tools.video.pixabay_video", "pixabay_video"),
    ("tools.enhancement.bg_remove", "bg_remove"),
    ("tools.graphics.threejs_asset_catalog", "threejs_asset_catalog"),
    ("tools.video.corpus_builder", "corpus_builder"),
    ("tools.video.direct_clip_search", "direct_clip_search"),
}
_DELEGATES = {
    ("tools.audio.tts_selector", "tts_selector"),
    ("tools.graphics.image_selector", "image_selector"),
    ("tools.video.video_selector", "video_selector"),
    ("tools.capture.screen_capture_selector", "screen_capture_selector"),
}


def requires_gate(tool, inputs):
    identity = (type(tool).__module__, tool.name)
    if identity in _DELEGATES or identity in _FREE:
        return False
    if identity == ("tools.graphics.image_gen", "image_gen"):
        # Never infer local from a missing price or changing credentials.
        return inputs.get("provider") != "local"
    if tool.provider == "comfyui":
        # A remote ComfyUI deployment can be a rented/billable GPU.
        host = urlparse(tool._client.server_url).hostname
        return host not in {"localhost", "127.0.0.1", "::1"}
    return getattr(tool.runtime, "value", tool.runtime) not in {"local", "local_gpu"}


def _canonical(value, key=""):
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise SpendingError("Request keys must be strings")
        return {k: _canonical(v, k) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(v, key) for v in value]
    if isinstance(value, os.PathLike):
        value = str(value)
    if isinstance(value, str) and key not in {"output_path", "job_path", "project_dir"}:
        try:
            path = Path(value)
            if path.is_file():
                h = hashlib.sha256()
                with path.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
                return {"path": str(path.resolve()), "sha256": h.hexdigest()}
        except (OSError, ValueError):
            # Path-shaped missing/unreadable media must not receive approval.
            if key.endswith(("_path", "_paths")):
                raise SpendingError("Cannot fingerprint input file")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SpendingError("Request contains an unsupported value")


def request_identity(tool, inputs):
    # Bind all inputs, defaults, tool implementation and provider-related env.
    # Only hashes are persisted for credentials. Never persist the raw request.
    env = {k: v for k, v in os.environ.items() if k.endswith(
        ("_KEY", "_TOKEN", "_URL", "_ENDPOINT", "_MODEL", "_REGION"))}
    sources = {}
    for cls in type(tool).__mro__:
        if cls is object:
            continue
        file = inspect.getsourcefile(cls)
        if file:
            sources[cls.__module__] = hashlib.sha256(Path(file).read_bytes()).hexdigest()
    context = {"tool": tool.name, "provider": tool.provider, "version": tool.version,
               "inputs": _canonical(inputs), "schema": tool.input_schema,
               "sources": sources, "environment": _digest(env),
               "cwd": str(Path.cwd().resolve()),
               "server_url": getattr(getattr(tool, "_client", None), "server_url", None)}
    if (type(tool).__module__, tool.name) == ("tools.graphics.image_gen", "image_gen"):
        context["resolved_provider"] = inputs.get("provider") or tool._detect_provider()
    try:
        return _digest(context)
    except (ValueError, TypeError) as exc:
        raise SpendingError("Cannot fingerprint request") from exc


def estimated_cost(tool, inputs):
    try:
        estimate = tool.estimate_cost(inputs)
    except PriceQuoteRequired:
        return None
    except Exception as exc:
        raise SpendingError("Cost estimator failed; paid execution blocked") from exc
    # Zero on a potential paid path is NOT evidence of free execution.
    if isinstance(estimate, bool):
        raise SpendingError("Boolean is not a cost estimate")
    if estimate is None or estimate == 0:
        return None
    return money(estimate, positive=True)


class Ledger:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).resolve()
        self.directory = self.root / ".openmontage-spending"
        self.path = self.directory / "ledger.sqlite3"

    def initialize(self, *, opening_spend_usd, evidence):
        """Explicit operator setup; never auto-reset a missing/corrupt ledger."""
        opening = money(opening_spend_usd)
        if not isinstance(evidence, str) or not evidence.strip():
            raise SpendingError("Opening balance review evidence is required")
        policy(self.root)
        self.directory.mkdir(mode=0o700, exist_ok=False)
        identity = uuid.uuid4().hex
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                PRAGMA synchronous=FULL;
                CREATE TABLE meta(identity TEXT, opening INTEGER NOT NULL);
                CREATE TABLE requests(
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    summary TEXT NOT NULL, estimate INTEGER NOT NULL,
                    ceiling INTEGER NOT NULL, expires REAL NOT NULL,
                    state TEXT NOT NULL, charge INTEGER NOT NULL DEFAULT 0,
                    reported INTEGER, provider_job TEXT, evidence TEXT);
                CREATE TABLE audit(at REAL NOT NULL, request_id TEXT,
                    action TEXT NOT NULL, detail TEXT NOT NULL);
            ''')
            db.execute("INSERT INTO meta VALUES (?,?)", (identity, opening))
            self._audit(db, None, "initialize", evidence)
        os.chmod(self.path, 0o600)
        marker = self.directory / "identity"
        with marker.open("x") as file:
            file.write(identity)
            file.flush()
            os.fsync(file.fileno())

    @contextmanager
    def transaction(self):
        db = None
        try:
            identity = (self.directory / "identity").read_text().strip()
            # mode=rw is critical: a missing ledger must NEVER create a new one.
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM meta").fetchall()
            if len(rows) != 1 or rows[0]["identity"] != identity:
                raise SpendingError("Spending ledger identity mismatch")
            yield db
            db.commit()
        except (OSError, sqlite3.Error) as exc:
            raise SpendingError("Spending ledger unavailable; paid execution blocked") from exc
        finally:
            if db is not None:
                db.close()  # uncommitted operations roll back, including exceptions

    @staticmethod
    def _audit(db, request_id, action, detail):
        db.execute("INSERT INTO audit VALUES (?,?,?,?)",
                   (time.time(), request_id, action, str(detail)))

    @staticmethod
    def _get(db, request_id):
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise SpendingError("Unknown spending request")
        return dict(row)

    def quote(self, tool, inputs, *, ceiling_usd=None, quoted_usd=None, evidence=None):
        if not requires_gate(tool, inputs):
            return {"tool": tool.name, "estimated_usd": 0, "approval_required": False}
        estimate = estimated_cost(tool, inputs)
        source = "estimator" if estimate is not None else "provider_quote"
        if estimate is None:
            if quoted_usd is None or not evidence or not str(evidence).strip():
                raise PriceQuoteRequired("A current, request-specific provider quote and evidence are required")
            estimate = money(quoted_usd, positive=True)
        elif quoted_usd is not None:
            raise SpendingError("Do not override a working estimator")
        ceiling = estimate if ceiling_usd is None else money(ceiling_usd, positive=True)
        if ceiling < estimate:
            raise SpendingError("Approved maximum cannot be below the estimate")
        fingerprint = request_identity(tool, inputs)
        properties = tool.input_schema.get("properties", {})
        model = inputs.get("model", inputs.get("model_id"))
        if model is None:
            model = properties.get("model", {}).get("default", properties.get("model_id", {}).get("default"))
        units = {key: inputs[key] for key in ("duration", "duration_seconds", "n", "num_images",
                 "number_of_images", "resolution", "quality") if key in inputs}
        if isinstance(inputs.get("text"), str):
            units["text_characters"] = len(inputs["text"])
        summary = {"tool": tool.name, "provider": tool.provider,
                   "model": model or "tool default; bound to request hash", "units": units,
                   "operation": inputs.get("operation", "execute"),
                   "estimated_usd": estimate / SCALE, "maximum_usd": ceiling / SCALE,
                   "request_sha256": fingerprint, "quote_evidence": evidence, "estimate_source": source,
                   "expires_in_seconds": 900, "approval_required": True}
        identifier = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("INSERT INTO requests(id,fingerprint,summary,estimate,ceiling,expires,state) "
                       "VALUES (?,?,?,?,?,?,?)", (identifier, fingerprint, _dump(summary),
                       estimate, ceiling, time.time() + 900, "quoted"))
            self._audit(db, identifier, "quote", _dump(summary))
        return {"id": identifier, **summary}

    def show(self, identifier):
        with self.transaction() as db:
            return self._get(db, identifier)

    def approve(self, identifier, *, evidence):
        """Operator-only transition; CLI requires an exact interactive phrase."""
        if not isinstance(evidence, str) or not evidence.strip():
            raise SpendingError("Explicit human approval evidence is required")
        with self.transaction() as db:
            row = self._get(db, identifier)
            if row["state"] != "quoted" or row["expires"] <= time.time():
                raise SpendingError("Quote expired or already used")
            self._check_budget(db, row["ceiling"])
            db.execute("UPDATE requests SET state='approved',evidence=? WHERE id=?", (evidence, identifier))
            self._audit(db, identifier, "approve", evidence)

    def _check_budget(self, db, ceiling):
        limits = policy(self.root)  # re-read every approval/reservation; no stale cache
        if db.execute("SELECT 1 FROM requests WHERE state IN ('unresolved','overrun') LIMIT 1").fetchone():
            raise SpendingError("Unresolved provider billing blocks further paid execution; reconcile first")
        opening = db.execute("SELECT opening FROM meta").fetchone()[0]
        used = db.execute("SELECT COALESCE(SUM(charge),0) FROM requests").fetchone()[0] + opening
        if ceiling > limits["maximum"] or used + ceiling > limits["total"]:
            raise BudgetExceededError(
                f"Maximum ${ceiling / SCALE:.6f} exceeds available budget "
                f"${max(0, limits['total'] - used) / SCALE:.6f} or per-action limit "
                f"${limits['maximum'] / SCALE:.6f}")

    def reserve(self, tool, inputs, identifier):
        fingerprint = request_identity(tool, inputs)
        estimate = estimated_cost(tool, inputs)
        with self.transaction() as db:
            row = self._get(db, identifier)
            if row["state"] != "approved" or row["expires"] <= time.time():
                raise ApprovalRequiredError("Approval expired or already consumed; no paid call made")
            if row["fingerprint"] != fingerprint:
                raise ApprovalRequiredError("Request changed; obtain a fresh quote and approval")
            if estimate is None and json.loads(row["summary"])["estimate_source"] != "provider_quote":
                raise PriceQuoteRequired("Cost became unknown; obtain a fresh provider quote")
            if estimate is not None and estimate != row["estimate"]:
                raise ApprovalRequiredError("Cost estimate changed; obtain a fresh quote and approval")
            if db.execute("SELECT 1 FROM requests WHERE fingerprint=? AND state='reserved'",
                          (fingerprint,)).fetchone():
                raise SpendingError("This request is already in flight or interrupted; reconcile first")
            self._check_budget(db, row["ceiling"])
            db.execute("UPDATE requests SET state='reserved',charge=ceiling WHERE id=?", (identifier,))
            self._audit(db, identifier, "reserve", "Approval consumed before provider execution")
        # transaction committed BEFORE returning to the provider

    def finish(self, identifier, result=None):
        actual = getattr(result, "cost_usd", None)
        try:
            reported = money(actual, positive=True)
        except SpendingError:
            reported = None
        with self.transaction() as db:
            row = self._get(db, identifier)
            if row["state"] != "reserved":
                raise SpendingError("Reservation changed during execution")
            good = result is not None and getattr(result, "success", False) is True
            state = "completed" if good and reported is not None else "unresolved"
            charge = max(row["ceiling"], reported or 0)
            if reported is not None and reported > row["ceiling"]:
                state = "overrun"
            data = getattr(result, "data", {}) or {}
            job = {k: data[k] for k in ("job_id", "task_id", "request_id") if isinstance(data.get(k), str)}
            if isinstance(data.get("resume_job"), dict):
                job.update({k: data["resume_job"][k] for k in ("id", "job_id", "task_id", "request_id")
                            if isinstance(data["resume_job"].get(k), str)})
            db.execute("UPDATE requests SET state=?,charge=?,reported=?,provider_job=? WHERE id=?",
                       (state, charge, reported, _dump(job), identifier))
            self._audit(db, identifier, state, "Maximum retained until verified billing reconciliation")
        if state in {"unresolved", "overrun"}:
            raise SpendingError(f"Request {identifier}: {state}; do not resubmit. Reconcile provider billing")

    def reconcile(self, identifier, *, actual_usd, evidence):
        actual = money(actual_usd)
        if not isinstance(evidence, str) or not evidence.strip():
            raise SpendingError("Provider receipt/job or confirmed non-acceptance evidence required")
        with self.transaction() as db:
            row = self._get(db, identifier)
            if row["state"] not in {"reserved", "unresolved", "completed", "overrun"}:
                raise SpendingError("Only a submitted request can be reconciled")
            db.execute("UPDATE requests SET state='reconciled',charge=?,reported=?,evidence=? WHERE id=?",
                       (actual, actual, evidence, identifier))
            self._audit(db, identifier, "reconcile", evidence)

    def status(self):
        with self.transaction() as db:
            rows = [dict(r) for r in db.execute("SELECT id,state,charge,reported,provider_job FROM requests")]
            opening = db.execute("SELECT opening FROM meta").fetchone()[0]
        return {"accounted_usd": (opening + sum(r["charge"] for r in rows)) / SCALE,
                "requests": rows, "policy": policy(self.root)}


def require_active_spend(tool=None):
    """Known shared paid-submission helpers cannot be called outside execute()."""
    if _ACTIVE.get() is None or (tool is not None and _ACTIVE.get() is not tool):
        raise SpendingError("Direct paid helper blocked; use an approved BaseTool.execute request")


def guarded_provider_method(fn):
    """Protect common public/private provider entry points used by adapters."""
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        inputs = args[0] if args and isinstance(args[0], dict) else {}
        if requires_gate(self, inputs):
            require_active_spend(self)
        return fn(self, *args, **kwargs)
    return wrapped


def guarded_execute(fn):
    @functools.wraps(fn)
    def wrapped(self, inputs, *args, **kwargs):
        if not isinstance(inputs, dict):
            raise SpendingError("Tool inputs must be a dictionary")
        clean = copy.deepcopy(inputs)
        token = clean.pop("_spending_approval", None) or _TOKEN.get()
        context = _TOKEN.set(token)
        try:
            # Every provider invocation is gated, including nested calls and
            # recursion. Only reviewed delegates pass through without charging.
            if not requires_gate(self, clean):
                return fn(self, clean, *args, **kwargs)
            ledger = Ledger()
            if token is None:
                quote = ledger.quote(self, clean)
                raise ApprovalRequiredError("Paid call blocked. Review and approve: " + _dump(quote))
            if args or kwargs:
                raise SpendingError("Paid calls must bind all arguments in the input dictionary")
            ledger.reserve(self, clean, token)
            active = _ACTIVE.set(self)
            try:
                result = fn(self, clean, *args, **kwargs)
            except BaseException:
                # Keep the durable reservation even on cancellation/SystemExit.
                # Preserve the original error; ledger failure never refunds it.
                try:
                    ledger.finish(token)
                except SpendingError:
                    pass
                raise
            finally:
                _ACTIVE.reset(active)
            ledger.finish(token, result)
            return result
        finally:
            _TOKEN.reset(context)
    return wrapped
