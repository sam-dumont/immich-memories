"""The docs setup builder must emit files the app itself accepts."""

import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "docs-site/src/components/SetupBuilder"
SECRET = "a" * 64
COMBOS = [
    (p, t) for p in ("linux", "synology", "mac", "kubernetes") for t in ("basic", "gpu", "full")
]


def builder_outputs() -> dict:
    script = f"""
import {{readFileSync}} from 'node:fs';
import {{buildSetup}} from {json.dumps(str(BUILDER / "recipes.ts"))};
const sources = JSON.parse(readFileSync({json.dumps(str(BUILDER / "sources.json"))}, 'utf8'));
const out = {{}};
for (const platform of ['linux', 'synology', 'mac', 'kubernetes']) {{
  for (const tier of ['basic', 'gpu', 'full']) {{
    out[platform + '/' + tier] = buildSetup({{
      platform, tier, immichUrl: 'http://192.168.1.10:2283',
      gpuBox: '', readerUrl: tier === 'full' ? 'http://192.168.1.20:8000/v1' : '',
      readerModel: tier === 'full' ? 'gemma-4-E4B-it-Q4_0' : '', cuda: false,
      version: '1.2.3', secretKey: {json.dumps(SECRET)},
    }}, sources, '1.2.3');
  }}
}}
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


OUTPUTS = builder_outputs()


@pytest.mark.parametrize(("platform", "tier"), COMBOS)
def test_every_builder_output_is_accepted_by_the_app(platform, tier, tmp_path, monkeypatch):
    from immich_memories.config_loader import Config

    result = OUTPUTS[f"{platform}/{tier}"]
    assert result["error"] is None
    for file in result["files"]:
        name = file["name"]
        if name == "config.yaml":
            path = tmp_path / "config.yaml"
            path.write_text(file["content"])
            monkeypatch.setenv("HOME", str(tmp_path))
            Config.from_yaml(path)  # raises on a value the schema rejects
        elif name.endswith(".env"):
            keys = re.findall(r"^([A-Z_]+)=", file["content"], re.M)
            compose = next(f for f in result["files"] if f["name"].endswith("docker-compose.yml"))
            assert keys
            for key in keys:
                assert key in compose["content"] or key == "IMMICH_MEMORIES_VERSION", key
        else:
            assert yaml.safe_load(file["content"])


@pytest.mark.parametrize("tier", ["basic", "gpu", "full"])
def test_mac_move_to_db_names_only_keys_the_file_sets(tier):
    result = OUTPUTS[f"mac/{tier}"]
    config = yaml.safe_load(result["files"][0]["content"])
    line = next(line for line in result["commands"].splitlines() if "config move-to-db" in line)
    flat = {}

    def walk(node, prefix=""):
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value, f"{prefix}{key}.")
            else:
                flat[f"{prefix}{key}"] = value

    walk(config)
    flat.update({k.removeprefix("advanced."): v for k, v in flat.items()})
    for key in shlex.split(line)[3:]:
        assert key in flat, f"{key} is moved but config.yaml does not set it"


@pytest.mark.parametrize("tier", ["basic", "gpu", "full"])
def test_mac_commands_follow_the_uv_pip_page(tier):
    commands = OUTPUTS[f"mac/{tier}"]["commands"].splitlines()
    assert any(
        line.startswith("brew install uv ffmpeg") and "ffmpeg-full" not in line for line in commands
    )
    assert not any(line.startswith("export PATH") for line in commands)
    assert commands.index("umask 077") < next(
        i for i, line in enumerate(commands) if "Save the generated config.yaml" in line
    )
    assert commands[-1].endswith("ui --host 127.0.0.1 --port 8080")


@pytest.mark.parametrize("tier", ["basic", "gpu", "full"])
def test_kubernetes_namespace_is_one_value_everywhere(tier):
    result = OUTPUTS[f"kubernetes/{tier}"]
    docs = [
        yaml.safe_load(f["content"])
        for f in result["files"]
        if f["name"].endswith(("secret.yaml", "kustomization.yaml"))
    ]
    assert {d.get("namespace") or d["metadata"]["namespace"] for d in docs} == {"immich-memories"}
    assert "models fetch" in result["commands"]


PLACEHOLDER = "replace-with-your-immich-api-key"


def yaml_files():
    return [
        (key, f)
        for key, result in OUTPUTS.items()
        for f in result["files"]
        if f["name"].endswith((".yml", ".yaml"))
    ]


@pytest.mark.parametrize(
    ("key", "file"), yaml_files(), ids=lambda v: v if isinstance(v, str) else v["name"]
)
def test_yaml_outputs_are_block_yaml_with_the_data_the_json_had(key, file):
    assert not file["content"].lstrip().startswith(("{", "["))
    parsed = yaml.safe_load(file["content"])
    expected = file["data"]
    if file["name"].endswith("kustomization.yaml"):
        # The kustomize patches were JSON strings; they are YAML block scalars now.
        for patch in (*parsed["patches"], *expected["patches"]):
            patch["patch"] = yaml.safe_load(patch["patch"])
    assert parsed == expected


@pytest.mark.parametrize(("platform", "tier"), COMBOS)
def test_no_output_holds_a_key_and_the_placeholder_marks_where_it_goes(platform, tier):
    result = OUTPUTS[f"{platform}/{tier}"]
    text = "\n".join(f["content"] for f in result["files"])
    assert PLACEHOLDER in text
    assert "fake-key-for-tests" not in text
    assert "Put your Immich API key in" in result["commands"]


def test_emitter_round_trips_values_yaml_would_misread():
    tricky = [
        "127.0.0.1:8080:8080",
        "true",
        "false",
        "yes",
        "no",
        "null",
        "on",
        "off",
        "~",
        "Y",
        "8080",
        "1.2",
        "0x1f",
        "1e3",
        "-1",
        ".5",
        "2024-01-01",
        "",
        " lead",
        "a: b",
        "a #b",
        "a:",
        "*x",
        "&x",
        "!x",
        "{x}",
        "[x]",
        "- x",
        "%x",
        "@x",
        "`x",
        "|",
        ">",
        'say "hi"',
        "it's",
        "${IMMICH_MEMORIES_VERSION:-latest}",
        "a\nb",
        "tab\tx",
        "café",
        "\u2028",
        "back\\slash",
    ]
    data = {
        "strings": tricky,
        "by_key": {k: k for k in tricky if k != ""} | {"": "empty key"},
        "real": [True, False, 8080, 1.5, None, {}, []],
        "nested": [[1, 2], {"a": [{"b": 1}, {"c": {"d": []}}]}],
    }
    script = (
        f"import {{toYaml}} from {json.dumps(str(BUILDER / 'yaml.ts'))};\n"
        "console.log(JSON.stringify(toYaml(JSON.parse(process.argv[1]))));"
    )
    out = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            script,
            json.dumps(data),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert yaml.safe_load(json.loads(out.stdout)) == data
