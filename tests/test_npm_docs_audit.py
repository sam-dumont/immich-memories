"""Exercise the explicit docs-only advisory review, without weakening strict auditing."""

import json
import runpy
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/npm_docs_audit.py"


def with_metadata(report):
    counts = dict.fromkeys(["info", "low", "moderate", "high", "critical"], 0)
    for item in report["vulnerabilities"].values():
        counts[item["severity"]] += 1
    counts["total"] = len(report["vulnerabilities"])
    report["metadata"] = {"vulnerabilities": counts}
    return report


def test_strict_default_rejects_even_reviewed_advisories():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report = {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "braces": {
                "name": "braces",
                "severity": "high",
                "nodes": ["node_modules/braces"],
                "fixAvailable": False,
                "via": [
                    {
                        "name": "braces",
                        "severity": "high",
                        "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                    }
                ],
            }
        },
    }
    lock = {"packages": {"node_modules/braces": {"version": "3.0.3"}}}
    assert evaluate(with_metadata(report), lock, reviewed=False, today=date(2026, 10, 3)) == 1
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 0


def test_malformed_low_report_cannot_be_mistaken_for_clean():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    assert (
        evaluate(
            {"auditReportVersion": 2, "vulnerabilities": {"mystery": {"severity": "unknown"}}},
            {"packages": {}},
            reviewed=True,
            today=date(2026, 10, 3),
        )
        == 2
    )


def reviewed_report():
    report = {"auditReportVersion": 2, "vulnerabilities": {}}
    packages = {}
    for name, version, advisory in [
        ("braces", "3.0.3", "GHSA-vfj7-8cjw-p6xm"),
    ]:
        path = f"node_modules/{name}"
        packages[path] = {"version": version}
        report["vulnerabilities"][name] = {
            "name": name,
            "severity": "high",
            "nodes": [path],
            "fixAvailable": False,
            "via": [
                {
                    "name": name,
                    "severity": "high",
                    "url": f"https://github.com/advisories/{advisory}",
                }
            ],
        }
    report["vulnerabilities"]["docusaurus"] = {
        "name": "docusaurus",
        "severity": "high",
        "nodes": ["node_modules/docusaurus"],
        "fixAvailable": False,
        "via": ["braces"],
    }
    packages["node_modules/docusaurus"] = {"version": "3.10.2"}
    return report, {"packages": packages}


def test_only_exact_unfixed_graph_is_accepted_until_expiry():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = reviewed_report()
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 16)) == 0
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 17)) == 1
    lock["packages"]["node_modules/braces"]["version"] = "3.0.4"
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_http_cache_semantics_review_is_retired_once_patched():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = reviewed_report()
    lock["packages"]["node_modules/http-cache-semantics"] = {"version": "4.2.0"}
    report["vulnerabilities"]["http-cache-semantics"] = {
        "name": "http-cache-semantics",
        "severity": "high",
        "nodes": ["node_modules/http-cache-semantics"],
        "fixAvailable": False,
        "via": [
            {
                "name": "http-cache-semantics",
                "severity": "high",
                "url": "https://github.com/advisories/GHSA-ch52-4w7c-c8xp",
            }
        ],
    }
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 4)) == 1


def test_new_fixable_and_critical_advisories_are_refused():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    for change in ["fix", "advisory", "critical"]:
        report, lock = reviewed_report()
        node = report["vulnerabilities"]["braces"]
        if change == "fix":
            node["fixAvailable"] = {"name": "braces", "version": "3.0.4"}
        elif change == "advisory":
            node["via"][0]["url"] = "https://github.com/advisories/GHSA-new"
        else:
            node["severity"] = "critical"
        assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_missing_lock_paths_unknown_graph_and_cycles_fail_closed():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    for change in ["path", "graph", "cycle", "format"]:
        report, lock = reviewed_report()
        if change == "path":
            del lock["packages"]["node_modules/braces"]
        elif change == "graph":
            report["vulnerabilities"]["docusaurus"]["via"] = ["unknown"]
        elif change == "cycle":
            report["vulnerabilities"]["braces"]["via"] = ["braces"]
        else:
            report["auditReportVersion"] = 3
        assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 2


def test_cli_crashes_and_malformed_json_never_pass(tmp_path):
    import subprocess
    import sys

    report, lock = reviewed_report()
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    command = [sys.executable, str(SCRIPT), "--reviewed", "--lock", str(path)]
    for payload, code in [
        (json.dumps(with_metadata(report)), "2"),
        (json.dumps(with_metadata(report)), "0"),
        ("not json", "1"),
    ]:
        result = subprocess.run(
            command + ["--audit-exit", code], input=payload, text=True, capture_output=True
        )
        assert result.returncode == 2
        assert "refused" in result.stdout


def test_npm_boolean_metavulnerability_remediation_does_not_claim_a_leaf_fix():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = reviewed_report()
    report["vulnerabilities"]["docusaurus"]["fixAvailable"] = True
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 0
    report["vulnerabilities"]["docusaurus"]["fixAvailable"] = {
        "name": "docusaurus",
        "version": "4.0.0",
    }
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_dependency_cycles_need_a_reviewed_leaf_and_do_not_hide_other_leaves():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = reviewed_report()
    node = report["vulnerabilities"]["docusaurus"]
    node["via"].append("docusaurus")
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 0
    node["via"] = ["docusaurus"]
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 2


def test_missing_or_contradictory_metadata_and_wrong_package_paths_fail():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    assert (
        evaluate(
            {"auditReportVersion": 2, "vulnerabilities": {}},
            {"packages": {}},
            reviewed=True,
            today=date(2026, 10, 3),
        )
        == 2
    )
    report, lock = reviewed_report()
    with_metadata(report)
    report["metadata"]["vulnerabilities"]["high"] = 0
    assert evaluate(report, lock, reviewed=True, today=date(2026, 10, 3)) == 2
    report, lock = reviewed_report()
    report["vulnerabilities"]["braces"]["nodes"] = ["node_modules/not-braces"]
    lock["packages"]["node_modules/not-braces"] = {"version": "3.0.3"}
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 2


def test_critical_source_cannot_hide_under_high_parent():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = reviewed_report()
    report["vulnerabilities"]["braces"]["via"][0]["severity"] = "critical"
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_make_default_uses_approved_review_and_explicit_strict_still_refuses(tmp_path):
    import os
    import subprocess

    report, _ = reviewed_report()
    report["vulnerabilities"] = {"braces": report["vulnerabilities"]["braces"]}
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps(with_metadata(report)))
    npm = tmp_path / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'case "$PWD" in */web) exit 0 ;; esac\n'
        'case "$*" in *--json*) cat "$AUDIT_FIXTURE" ;; esac\n'
        "exit 1\n"
    )
    npm.chmod(0o700)
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "AUDIT_FIXTURE": str(audit),
    }
    root = SCRIPT.parent.parent
    reviewed = subprocess.run(["make", "npm-audit"], cwd=root, env=env, capture_output=True)
    assert reviewed.returncode == 0, reviewed.stderr.decode()
    strict = subprocess.run(["make", "npm-audit-strict"], cwd=root, env=env, capture_output=True)
    assert strict.returncode != 0
