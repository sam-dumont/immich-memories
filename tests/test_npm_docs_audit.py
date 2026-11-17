"""Exercise the explicit, dated advisory review of the client and docs npm audits."""

import json
import runpy
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/npm_docs_audit.py"


BRACES_REVIEW = ("braces", "3.0.3", "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm")
PICOMATCH = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
EXPIRES = runpy.run_path(str(SCRIPT))["EXPIRES"]


def with_review(review=BRACES_REVIEW):
    """The script's `evaluate`, with one review open, so the machinery is tested on its own.

    `run_path` returns a copy of the module's globals, so the set itself is filled in place: the
    function reads that same object, and every call gets a fresh one.
    """
    namespace = runpy.run_path(str(SCRIPT))
    namespace["REVIEWED"].add(review)
    return namespace["evaluate"]


def test_only_the_build_only_picomatch_advisory_is_reviewed_until_december_17():
    script = runpy.run_path(str(SCRIPT))
    assert script["REVIEWED"] == {
        ("picomatch", "2.3.2", PICOMATCH),
        ("picomatch", "4.0.7", PICOMATCH),
    }
    assert script["EXPIRES"] == date(2026, 12, 17)


def with_metadata(report):
    counts = dict.fromkeys(["info", "low", "moderate", "high", "critical"], 0)
    for item in report["vulnerabilities"].values():
        counts[item["severity"]] += 1
    counts["total"] = len(report["vulnerabilities"])
    report["metadata"] = {"vulnerabilities": counts}
    return report


def test_strict_default_rejects_even_reviewed_advisories():
    evaluate = with_review()
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
    evaluate = with_review()
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
    evaluate = with_review()
    report, lock = reviewed_report()
    assert evaluate(with_metadata(report), lock, reviewed=True, today=EXPIRES - timedelta(1)) == 0
    assert evaluate(with_metadata(report), lock, reviewed=True, today=EXPIRES) == 1
    lock["packages"]["node_modules/braces"]["version"] = "3.0.4"
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_http_cache_semantics_review_is_retired_once_patched():
    evaluate = with_review()
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
    evaluate = with_review()
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
    evaluate = with_review()
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
    evaluate = with_review()
    report, lock = reviewed_report()
    report["vulnerabilities"]["docusaurus"]["fixAvailable"] = True
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 0
    report["vulnerabilities"]["docusaurus"]["fixAvailable"] = {
        "name": "docusaurus",
        "version": "4.0.0",
    }
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def test_dependency_cycles_need_a_reviewed_leaf_and_do_not_hide_other_leaves():
    evaluate = with_review()
    report, lock = reviewed_report()
    node = report["vulnerabilities"]["docusaurus"]
    node["via"].append("docusaurus")
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 0
    node["via"] = ["docusaurus"]
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 2


def test_missing_or_contradictory_metadata_and_wrong_package_paths_fail():
    evaluate = with_review()
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
    evaluate = with_review()
    report, lock = reviewed_report()
    report["vulnerabilities"]["braces"]["via"][0]["severity"] = "critical"
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 10, 3)) == 1


def finding(name, via, fix, nodes=None):
    return {
        "name": name,
        "severity": "high",
        "nodes": nodes or [f"node_modules/{name}"],
        "fixAvailable": fix,
        "via": via,
    }


def picomatch_leaf(url=PICOMATCH):
    return {"name": "picomatch", "severity": "high", "url": url, "range": "<=4.0.7"}


def web_picomatch_report():
    """The client audit as npm prints it: picomatch has no patched release, so each concrete
    offer is a downgrade of a direct dependency to an older major."""
    findings = [
        finding("picomatch", [picomatch_leaf()], {"name": "vite", "version": "6.2.7"}),
        finding("fdir", ["picomatch"], {"name": "svelte-check", "version": "3.8.6"}),
        finding("tinyglobby", ["fdir", "picomatch"], True),
        finding("vite", ["picomatch", "tinyglobby"], {"name": "vite", "version": "6.2.7"}),
        finding("svelte-check", ["fdir"], {"name": "svelte-check", "version": "3.8.6"}),
    ]
    report = {"auditReportVersion": 2, "vulnerabilities": {f["name"]: f for f in findings}}
    locked = {
        "picomatch": "4.0.7",
        "fdir": "6.5.0",
        "tinyglobby": "0.2.17",
        "vite": "8.3.7",
        "svelte-check": "4.7.8",
    }
    packages = {f"node_modules/{name}": {"version": v} for name, v in locked.items()}
    return report, {"packages": packages}


def docs_picomatch_report():
    """The docs audit: picomatch 2.3.2 at top level, 4.0.7 under tinyglobby and vite."""
    paths = [
        "node_modules/picomatch",
        "node_modules/tinyglobby/node_modules/picomatch",
        "node_modules/vite/node_modules/picomatch",
    ]
    findings = [
        finding("picomatch", [picomatch_leaf()], False, paths),
        finding("micromatch", ["picomatch"], False),
        finding("tinyglobby", ["picomatch"], True),
    ]
    report = {"auditReportVersion": 2, "vulnerabilities": {f["name"]: f for f in findings}}
    versions = ["2.3.2", "4.0.7", "4.0.7"]
    packages = {path: {"version": v} for path, v in zip(paths, versions, strict=True)}
    packages["node_modules/micromatch"] = {"version": "4.0.8"}
    packages["node_modules/tinyglobby"] = {"version": "0.2.17"}
    return report, {"packages": packages}


def test_picomatch_and_its_dependents_pass_both_audits_until_the_review_expires():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    for report, lock in [web_picomatch_report(), docs_picomatch_report()]:
        with_metadata(report)
        assert evaluate(report, lock, reviewed=True, today=EXPIRES - timedelta(1)) == 0
        assert evaluate(report, lock, reviewed=True, today=EXPIRES) == 1
        assert evaluate(report, lock, reviewed=False, today=EXPIRES - timedelta(1)) == 1


def test_another_advisory_an_unlisted_version_or_a_real_fix_still_fails():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    other = {"name": "vite", "severity": "high", "url": "https://github.com/advisories/GHSA-x"}
    upgrade = {"name": "vite", "version": "9.0.0", "isSemVerMajor": True}
    changes = [
        ("picomatch", "via", [picomatch_leaf("https://github.com/advisories/GHSA-new")]),
        ("vite", "via", ["picomatch", "tinyglobby", other]),
        ("picomatch", "fixAvailable", True),
        ("picomatch", "fixAvailable", {"name": "picomatch", "version": "4.0.8"}),
        ("vite", "fixAvailable", upgrade),
    ]
    for name, key, value in changes:
        report, lock = web_picomatch_report()
        report["vulnerabilities"][name][key] = value
        assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 11, 17)) == 1
    report, lock = web_picomatch_report()
    lock["packages"]["node_modules/picomatch"]["version"] = "4.0.6"
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 11, 17)) == 1


def test_a_downgrade_offer_with_an_unreadable_version_is_inconclusive():
    evaluate = runpy.run_path(str(SCRIPT))["evaluate"]
    report, lock = web_picomatch_report()
    report["vulnerabilities"]["vite"]["fixAvailable"] = {"name": "vite", "version": "latest"}
    assert evaluate(with_metadata(report), lock, reviewed=True, today=date(2026, 11, 17)) == 2


def test_make_runs_the_client_and_docs_audits_through_the_review(tmp_path):
    import os
    import subprocess

    npm = tmp_path / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'case "$PWD" in\n'
        '  */web) side=web fixture="$WEB_FIXTURE" code="$WEB_EXIT" ;;\n'
        '  *) side=docs fixture="$DOCS_FIXTURE" code="$DOCS_EXIT" ;;\n'
        "esac\n"
        'echo "$side $*" >> "$NPM_CALLS"\n'
        'case "$*" in *--json*) cat "$fixture" ;; esac\n'
        'exit "$code"\n'
    )
    npm.chmod(0o700)
    root = SCRIPT.parent.parent
    calls = tmp_path / "calls"

    def audit(web, docs, target="npm-audit"):
        env = os.environ | {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}
        env["NPM_CALLS"] = str(calls)
        for side, report in [("WEB", web), ("DOCS", docs)]:
            fixture = tmp_path / f"{side}.json"
            fixture.write_text(json.dumps(with_metadata(report)))
            env[f"{side}_FIXTURE"] = str(fixture)
            env[f"{side}_EXIT"] = str(int(bool(report["metadata"]["vulnerabilities"]["high"])))
        calls.write_text("")
        return subprocess.run(["make", target], cwd=root, env=env, capture_output=True)

    clean = {"auditReportVersion": 2, "vulnerabilities": {}}
    passed = audit(clean, clean)
    assert passed.returncode == 0, passed.stdout.decode() + passed.stderr.decode()
    assert calls.read_text().splitlines() == [
        "web audit --audit-level=high --json",
        "docs audit --omit=dev --audit-level=high --json",
    ]

    web, _ = web_picomatch_report()
    docs, _ = docs_picomatch_report()
    reviewed = audit(web, docs)
    assert (reviewed.returncode == 0) == (date.today() < EXPIRES), reviewed.stdout.decode()
    assert audit(web, docs, "npm-audit-strict").returncode != 0

    other, _ = web_picomatch_report()
    other["vulnerabilities"]["picomatch"]["via"] = [picomatch_leaf("https://x.test/GHSA-new")]
    assert audit(other, clean).returncode != 0
    assert audit(clean, other).returncode != 0
