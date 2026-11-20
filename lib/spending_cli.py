"""Operator interface: quote, explicitly approve, execute, inspect, reconcile.

Approval/reconciliation require a TTY and an exact phrase, not an env flag or
an input payload boolean. Only execute can call a provider. All other commands
are local; quote uses the provider's offline estimator.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from lib.spending import Ledger, SpendingError


def confirm(phrase):
    if not sys.stdin.isatty():
        raise SpendingError("Human confirmation requires an interactive terminal")
    if input(f"Type exactly {phrase!r}: ") != phrase:
        raise SpendingError("Confirmation did not match; no approval recorded")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--opening-spend", required=True)
    init.add_argument("--evidence", required=True)
    for name in ("quote", "execute"):
        sub = commands.add_parser(name)
        sub.add_argument("tool")
        sub.add_argument("inputs", type=Path)
        if name == "quote":
            sub.add_argument("--maximum")
            sub.add_argument("--quoted-usd")
            sub.add_argument("--evidence")
        else:
            sub.add_argument("--approval", required=True)
    for name in ("show", "approve", "reconcile"):
        sub = commands.add_parser(name)
        sub.add_argument("id")
        if name != "show":
            sub.add_argument("--evidence", required=True)
        if name == "reconcile":
            sub.add_argument("--actual-usd", required=True)
    commands.add_parser("status")
    args = parser.parse_args(argv)
    ledger = Ledger()
    if args.command == "init":
        confirm(f"INITIALIZE {args.opening_spend} USD")
        ledger.initialize(opening_spend_usd=args.opening_spend, evidence=args.evidence)
        output = ledger.status()
    elif args.command in {"quote", "execute"}:
        from tools.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.discover()
        tool = registry.get(args.tool)
        if tool is None:
            raise SpendingError("Unknown tool")
        inputs = json.loads(args.inputs.read_text())
        if not isinstance(inputs, dict) or "_spending_approval" in inputs:
            raise SpendingError("Inputs must be an object without embedded approval")
        if args.command == "quote":
            output = ledger.quote(tool, inputs, ceiling_usd=args.maximum,
                                  quoted_usd=args.quoted_usd, evidence=args.evidence)
        else:
            result = tool.execute({**inputs, "_spending_approval": args.approval})
            output = {"success": result.success, "data": result.data, "error": result.error}
    elif args.command == "status":
        output = ledger.status()
    else:
        row = ledger.show(args.id)
        print(json.dumps(row, indent=2))
        if args.command == "approve":
            confirm(f"APPROVE {args.id} {row['ceiling'] / 1_000_000:.6f} USD")
            ledger.approve(args.id, evidence=args.evidence)
        elif args.command == "reconcile":
            confirm(f"RECONCILE {args.id} {args.actual_usd} USD")
            ledger.reconcile(args.id, actual_usd=args.actual_usd, evidence=args.evidence)
        output = ledger.show(args.id)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Spending control: {exc}", file=sys.stderr)
        sys.exit(1)
