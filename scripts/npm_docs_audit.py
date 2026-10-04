#!/usr/bin/env python3
"""Fail closed; permit one time-limited docs review only with explicit opt-in."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

EXPIRES = date(2026, 10, 17)
REVIEWED = {
    ("braces", "3.0.3", "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm"),
}
SEVERITIES = {"info", "low", "moderate", "high", "critical"}


def _versions(node: dict, packages: dict) -> set[str]:
    paths = node["nodes"]
    if not isinstance(paths, list) or not paths:
        raise ValueError("missing audited package paths")
    if not all(
        isinstance(path, str) and path.endswith("node_modules/" + node["name"]) for path in paths
    ):
        raise ValueError("wrong audited package path")
    versions = {packages[path]["version"] for path in paths}
    if not all(isinstance(version, str) for version in versions):
        raise ValueError("invalid locked version")
    return versions


def _allowed(
    name: str, findings: dict, packages: dict, visiting: set[str], leaves: set[str]
) -> bool:
    if name in visiting:
        return True
    node = findings[name]
    if node["name"] != name or node["severity"] not in SEVERITIES:
        raise ValueError("invalid advisory identity or severity")
    versions = _versions(node, packages)
    if isinstance(node["fixAvailable"], dict):
        return False
    via = node["via"]
    if not isinstance(via, list) or not via:
        raise ValueError("missing advisory evidence")
    if node["severity"] == "critical":
        return False
    allowed = True
    for source in via:
        if isinstance(source, str):
            allowed = _allowed(source, findings, packages, visiting | {name}, leaves) and allowed
        elif isinstance(source, dict):
            leaves.add(name)
            if node["fixAvailable"] is not False:
                return False
            if source["severity"] == "critical":
                return False
            if source["name"] != name or source["severity"] not in SEVERITIES:
                raise ValueError("invalid advisory source")
            allowed = (
                all((name, version, source["url"]) in REVIEWED for version in versions) and allowed
            )
        else:
            raise ValueError("invalid advisory source")
    return allowed


def _accepted(name: str, findings: dict, packages: dict) -> bool:
    leaves: set[str] = set()
    accepted = _allowed(name, findings, packages, set(), leaves)
    if accepted and not leaves:
        raise ValueError("advisory graph has no leaf evidence")
    return accepted


def _validate_source(source: object, name: str, findings: dict) -> None:
    if isinstance(source, str):
        if source not in findings:
            raise ValueError("unknown advisory dependency")
    elif isinstance(source, dict):
        if source["name"] != name or source["severity"] not in SEVERITIES:
            raise ValueError("invalid advisory source")
        if not isinstance(source["url"], str):
            raise ValueError("invalid advisory URL")
    else:
        raise ValueError("invalid advisory source")


def evaluate(report: dict, lock: dict, *, reviewed: bool, today: date) -> int:
    """Return 0 for accepted findings, 1 for vulnerabilities, 2 for inconclusive input."""
    try:
        if report["auditReportVersion"] != 2 or "error" in report:
            raise ValueError("unsupported or failed npm audit")
        findings = report["vulnerabilities"]
        packages = lock["packages"]
        if not isinstance(findings, dict) or not isinstance(packages, dict):
            raise ValueError("invalid report or lock")
        for name, item in findings.items():
            if item["name"] != name or item["severity"] not in SEVERITIES:
                raise ValueError("invalid advisory identity or severity")
            _versions(item, packages)
            if not isinstance(item["via"], list) or not item["via"]:
                raise ValueError("missing advisory evidence")
            for source in item["via"]:
                _validate_source(source, name, findings)
            if not isinstance(item["fixAvailable"], (bool, dict)):
                raise ValueError("missing remediation evidence")
        counts = dict.fromkeys(SEVERITIES, 0)
        for item in findings.values():
            counts[item["severity"]] += 1
        counts["total"] = len(findings)
        if report["metadata"]["vulnerabilities"] != counts:
            raise ValueError("inconsistent audit counts")
        high = [
            name
            for name, item in findings.items()
            if item["severity"] in {"high", "critical"}
            or any(
                isinstance(source, dict) and source["severity"] in {"high", "critical"}
                for source in item["via"]
            )
        ]
        if not high:
            return 0
        if not reviewed or today >= EXPIRES:
            return 1
        return 0 if all(_accepted(name, findings, packages) for name in high) else 1
    except (KeyError, TypeError, ValueError):
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--audit-exit", type=int, required=True)
    parser.add_argument("--reviewed", action="store_true")
    args = parser.parse_args()
    try:
        report = json.load(sys.stdin)
        lock = json.loads(args.lock.read_text())
        result = evaluate(report, lock, reviewed=args.reviewed, today=date.today())
        counts = report["metadata"]["vulnerabilities"]
        expected_exit = int(bool(counts["high"] + counts["critical"]))
        if args.audit_exit != expected_exit:
            result = 2
    except (OSError, KeyError, TypeError, ValueError):
        result = 2
    print(
        {
            0: "Docs audit accepted at the existing high threshold.",
            1: "Unreviewed, fixable, changed or expired high advisory: refused.",
            2: "Inconclusive docs audit: refused.",
        }[result]
    )
    if result == 0 and args.reviewed:
        print(f"Explicit docs-only review expires {EXPIRES}; packages remain unpatched.")
    sys.exit(result)


if __name__ == "__main__":
    main()
