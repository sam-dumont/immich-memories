"""Setup choices produce usable files with explicit reader activation."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node required")


def _build(_sources=None, _build_version="1.2.3", **changes):
    setup = {
        "platform": "linux",
        "tier": "basic",
        "immichUrl": "http://192.168.1.10:2283",
        "apiKey": "synthetic-fixture-api-key",
        "gpuBox": "",
        "readerUrl": "",
        "readerModel": "",
        "cuda": False,
        "version": "1.2.3",
        **changes,
    }
    if setup["platform"] == "kubernetes":
        setup.setdefault("secretKey", "a" * 64)
    sources = {
        "base": {"services": {"immich-memories": {"image": "app:${IMMICH_MEMORIES_VERSION}"}}},
        "gpu": {"services": {"inference": {"image": "inference:${IMMICH_MEMORIES_VERSION}"}}},
        "full": {
            "services": {
                "immich-memories": {"environment": {"IMMICH_MEMORIES_DEPLOYMENT_TIER": "full"}}
            }
        },
        "cuda": {"services": {"inference": {"image": "inference:${IMMICH_MEMORIES_VERSION}-cuda"}}},
    }
    if _sources is not None:
        sources = _sources
    module = ROOT / "docs-site/src/components/SetupBuilder/recipes.ts"
    output = subprocess.check_output(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            f"import {{buildSetup}} from {json.dumps(module.as_uri())}; "
            "const data=JSON.parse(process.argv[1]); console.log(JSON.stringify(buildSetup(data.setup,data.sources,data.buildVersion)));",
            json.dumps({"setup": setup, "sources": sources, "buildVersion": _build_version}),
        ],
        text=True,
    )
    return json.loads(output)


def test_basic_builder_outputs_one_compose_and_version_variable():
    result = _build()
    files = {file["name"]: file["content"] for file in result["files"]}
    compose = yaml.safe_load(files["docker-compose.yml"])
    assert set(compose["services"]) == {"immich-memories"}
    assert "IMMICH_MEMORIES_VERSION=1.2.3" in files[".env"]
    assert "docker-compose.override.yml" not in result["commands"]
    assert result["commands"].index("models fetch") < result["commands"].index("preflight")


def test_full_cuda_builder_keeps_base_and_explicit_reader_opt_in():
    result = _build(
        tier="full",
        cuda=True,
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
    )
    files = {file["name"]: file["content"] for file in result["files"]}
    compose = yaml.safe_load(files["docker-compose.yml"])
    assert set(compose["services"]) == {"immich-memories", "inference"}
    assert compose["services"]["inference"]["image"].endswith("-cuda")
    assert "READER_ENABLED=true" in files[".env"]
    assert "READER_MODEL='served-model'" in files[".env"]


def test_release_candidate_builder_uses_its_release_asset_urls():
    result = _build(
        platform="kubernetes", tier="gpu", version="v1.0.0-rc.1", _build_version="1.0.0-rc.1"
    )
    assert "/releases/download/v1.0.0-rc.1/" in result["commands"]
    root = next(
        file for file in result["files"] if file["name"].endswith("custom/kustomization.yaml")
    )
    assert yaml.safe_load(root["content"])["resources"] == ["../overlays/tier-gpu", "secret.yaml"]
    assert "raw.githubusercontent.com" not in result["commands"]


@pytest.mark.parametrize(
    "values", [{"immichUrl": "javascript:alert(1)"}, {"apiKey": "two\nlines"}, {"tier": "full"}]
)
def test_builder_refuses_invalid_connection_fields(values):
    assert _build(**values)["error"]


def test_mac_builder_uses_native_tools_and_keeps_reader_enabled_explicit():
    result = _build(platform="mac", tier="full")
    assert "immich-memories[all-mac]" in result["commands"]
    assert "--with laya-mlx" in result["commands"]
    assert "brew install" in result["commands"]
    assert "llama.cpp" in result["commands"]
    assert "models fetch" in result["commands"]
    assert "immich-memories ui" in result["commands"]
    assert "docker compose" not in result["commands"]
    config = yaml.safe_load(result["files"][0]["content"])
    assert config["advanced"]["llm"]["enabled"] is True
    assert config["advanced"]["llm"]["base_url"] == ""
    assert "config move-to-db" in result["commands"]


@pytest.mark.parametrize("platform", ["linux", "mac"])
def test_preview_builder_requires_a_published_version_instead_of_installing_other_code(platform):
    result = _build(platform=platform, version="development", _build_version="development")
    assert (
        result["error"]
        == "This docs build has no published release. Use release docs to export setup files."
    )
    assert result["files"] == []
    assert result["commands"] == ""


def test_remote_gpu_builder_omits_local_model_containers_and_keeps_requested_tier():
    result = _build(tier="gpu", gpuBox="192.168.1.50")
    files = {file["name"]: file["content"] for file in result["files"]}
    assert set(yaml.safe_load(files["docker-compose.yml"])["services"]) == {"immich-memories"}
    assert "TIER=gpu" in files[".env"]
    assert "GPU_BOX='192.168.1.50'" in files[".env"]


@pytest.mark.parametrize(
    "values",
    [
        {"immichUrl": "http://photos.example\n.com"},
        {"readerUrl": "http://reader.example\r.lan"},
        {"gpuBox": "operator@192.168.1.50"},
        {"version": "1.2.3; echo unsafe"},
        {"platform": "kubernetes", "version": "development"},
    ],
)
def test_builder_rejects_unsupported_or_ambiguous_inputs(values):
    assert _build(**values)["error"]


def test_kubernetes_builder_preserves_supplied_credentials_and_reader_configuration():
    result = _build(
        platform="kubernetes",
        tier="full",
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
    )
    files = {file["name"]: yaml.safe_load(file["content"]) for file in result["files"]}
    secret = files["deploy/kubernetes/custom/secret.yaml"]
    assert secret["stringData"]["IMMICH_URL"] == "http://192.168.1.10:2283"
    assert secret["stringData"]["IMMICH_API_KEY"] == "synthetic-fixture-api-key"
    assert secret["stringData"]["IMMICH_MEMORIES_SECRET_KEY"] == "a" * 64
    assert files["deploy/kubernetes/custom/kustomization.yaml"]["resources"] == [
        "../overlays/tier-full",
        "secret.yaml",
    ]
    assert files["deploy/kubernetes/overlays/tier-full/reader-config.yaml"]["data"] == {
        "url": "http://reader.example.lan:8000/v1",
        "model": "served-model",
    }


@pytest.mark.parametrize("host", ["gpu.example.lan:9000", "2001:db8::50", "[2001:db8::50]:9000"])
def test_remote_gpu_builder_accepts_the_loader_supported_addresses(host):
    result = _build(tier="gpu", gpuBox=host)
    assert result["error"] is None
    env = next(file["content"] for file in result["files"] if file["name"] == ".env")
    assert f"GPU_BOX='{host}'" in env


@pytest.mark.parametrize(
    "tier,cuda,gpu_box",
    [
        ("basic", False, ""),
        ("gpu", False, ""),
        ("gpu", True, ""),
        ("full", True, ""),
        ("gpu", False, "192.168.1.50"),
        ("full", False, "192.168.1.50"),
    ],
)
def test_builder_single_file_is_real_compose_with_exact_shipped_sources(
    tmp_path, tier, cuda, gpu_box
):
    executable = shutil.which("docker-compose") or shutil.which("docker")
    if executable is None:
        pytest.skip("Docker Compose required")
    command = [executable] if Path(executable).name == "docker-compose" else [executable, "compose"]
    sources = json.loads((ROOT / "docs-site/src/components/SetupBuilder/sources.json").read_text())
    result = _build(
        _sources=sources,
        tier=tier,
        cuda=cuda,
        gpuBox=gpu_box,
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
    )
    for file in result["files"]:
        (tmp_path / file["name"]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file["name"]).write_text(file["content"])
    with (tmp_path / ".env").open("a") as stream:
        stream.write("\nIMMICH_MEMORIES_SECRET_KEY=" + "x" * 64 + "\n")
    config = json.loads(
        subprocess.check_output(
            [
                *command,
                "--env-file",
                str(tmp_path / ".env"),
                "-f",
                str(tmp_path / "docker-compose.yml"),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    services = config["services"]
    app = services["immich-memories"]
    assert app["image"].endswith(":1.2.3")
    assert app["environment"]["IMMICH_MEMORIES_DEPLOYMENT_TIER"] == tier
    assert app["environment"]["IMMICH_API_KEY"] == "synthetic-fixture-api-key"
    if tier == "full":
        assert app["environment"]["IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED"] == "true"
    if gpu_box or tier == "basic":
        assert set(services) == {"immich-memories"}
    else:
        assert services["immich-memories-inference"]["image"].endswith(
            ":1.2.3-cuda" if cuda else ":1.2.3"
        )
        assert "immich-memories-captioner" in services
        assert "immich-memories-caption-models" in services


def test_selected_stable_kubernetes_bundle_uses_its_exact_tag():
    result = _build(
        platform="kubernetes", tier="basic", version="0.101.0", _build_version="0.101.0"
    )
    assert "/releases/download/v0.101.0/immich-memories-deploy-0.101.0.tar.gz" in result["commands"]


def test_native_external_reader_requires_its_served_model_instead_of_local_default():
    result = _build(platform="mac", tier="full", readerUrl="http://reader.example.lan:8000/v1")
    assert result["error"]


def test_authenticated_reader_is_configured_before_preflight_on_native_mac():
    result = _build(
        platform="mac",
        tier="full",
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
        readerApiKey="synthetic-reader-token",
    )
    config = yaml.safe_load(result["files"][0]["content"])
    assert config["advanced"]["llm"]["api_key"] == "synthetic-reader-token"
    assert "llm.api_key" in result["commands"]
    assert result["commands"].index("secret-key") < result["commands"].index("config move-to-db")
    assert result["commands"].index("config move-to-db") < result["commands"].index("preflight")


def test_authenticated_reader_is_a_lower_priority_compose_default(tmp_path):
    sources = json.loads((ROOT / "docs-site/src/components/SetupBuilder/sources.json").read_text())
    result = _build(
        _sources=sources,
        tier="full",
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
        readerApiKey="synthetic-reader-token",
    )
    files = {file["name"]: file["content"] for file in result["files"]}
    compose = yaml.safe_load(files["docker-compose.yml"])
    env = compose["services"]["immich-memories"]["environment"]
    assert env["IMMICH_MEMORIES_DEPLOYMENT_READER_API_KEY"] == "${READER_API_KEY:-}"
    assert "IMMICH_MEMORIES_LLM__API_KEY" not in env
    assert "READER_API_KEY='synthetic-reader-token'" in files[".env"]


def test_kubernetes_reader_egress_uses_the_supplied_endpoint_port():
    result = _build(
        platform="kubernetes",
        tier="full",
        readerUrl="http://reader.example.lan:9999/v1",
        readerModel="served-model",
    )
    root = next(
        file for file in result["files"] if file["name"].endswith("custom/kustomization.yaml")
    )
    config = yaml.safe_load(root["content"])
    patch = yaml.safe_load(config["patches"][0]["patch"])
    assert {row["port"] for row in patch[0]["value"]["ports"]} == {2283, 9999}
    assert all(row["protocol"] == "TCP" for row in patch[0]["value"]["ports"])


def test_single_file_stack_export_needs_no_dotenv_and_preserves_literal_dollars(tmp_path):
    sources = json.loads((ROOT / "docs-site/src/components/SetupBuilder/sources.json").read_text())
    result = _build(
        _sources=sources,
        inline=True,
        secretKey="a" * 64,
        apiKey="synthetic-$TOKEN-${OTHER}-key",
        tier="full",
        cuda=True,
        readerUrl="http://reader.example.lan:8000/v1",
        readerModel="served-model",
    )
    assert result["error"] is None
    assert [file["name"] for file in result["files"]] == ["docker-compose.yml"]
    (tmp_path / "docker-compose.yml").write_text(result["files"][0]["content"])
    executable = shutil.which("docker-compose") or shutil.which("docker")
    if executable is None:
        pytest.skip("Docker Compose required")
    command = [executable] if Path(executable).name == "docker-compose" else [executable, "compose"]
    config = json.loads(
        subprocess.check_output(
            [
                *command,
                "--env-file",
                "/dev/null",
                "-f",
                str(tmp_path / "docker-compose.yml"),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    app = config["services"]["immich-memories"]
    assert app["image"].endswith(":1.2.3")
    # Compose re-escapes literal dollars when serializing its reusable config output.
    assert app["environment"]["IMMICH_API_KEY"] == "synthetic-$$TOKEN-$${OTHER}-key"
    assert app["environment"]["IMMICH_MEMORIES_SECRET_KEY"] == "a" * 64
    assert app["environment"]["IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED"] == "true"
    assert "openssl rand" not in result["commands"]
    assert all(volume["type"] != "bind" for volume in app["volumes"])
    assert any(
        volume["target"] == "/app/output" and volume["type"] == "volume"
        for volume in app["volumes"]
    )


def test_single_file_stack_export_refuses_an_empty_settings_key():
    assert _build(inline=True)["error"]


def test_remote_gpu_setup_outputs_the_real_worker_with_matching_port_and_version(tmp_path):
    sources = json.loads((ROOT / "docs-site/src/components/SetupBuilder/sources.json").read_text())
    result = _build(_sources=sources, tier="gpu", gpuBox="gpu.example.lan:9000")
    files = {file["name"]: file["content"] for file in result["files"]}
    worker = yaml.safe_load(files["gpu-worker/docker-compose.yml"])
    assert worker["services"]["gpu-worker"]["ports"] == [
        "${GPU_WORKER_BIND_ADDRESS:-127.0.0.1}:9000:8092"
    ]
    assert "IMMICH_MEMORIES_VERSION=1.2.3" in files["gpu-worker/.env"]
    assert "IMMICH_URL='http://192.168.1.10:2283'" in files["gpu-worker/.env"]
    assert "RENDER_WORKER_TOKEN" in result["workerCommands"]
    assert "RENDER_WORKER_TOKEN" not in result["commands"]
    assert "mkdir -p immich-memories/output" not in result["workerCommands"]
    assert "render/health" in worker["services"]["gpu-worker"]["healthcheck"]["test"][-1]
    app = yaml.safe_load(files["docker-compose.yml"])["services"]["immich-memories"]
    assert "IMMICH_MEMORIES_RENDER__WORKER_BASE_URL" not in app["environment"]


@pytest.mark.parametrize("tier", ["basic", "gpu", "full"])
def test_generated_kubernetes_inputs_render_the_current_shipped_base(tmp_path, tier):
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl required")
    shutil.copytree(ROOT / "deploy/kubernetes", tmp_path / "deploy/kubernetes")
    result = _build(
        platform="kubernetes",
        tier=tier,
        readerUrl="http://reader.example.lan:9999/v1",
        readerModel="served-model",
        readerApiKey="synthetic-reader-token",
    )
    for file in result["files"]:
        path = tmp_path / file["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file["content"])
    resources = list(
        yaml.safe_load_all(
            subprocess.check_output(
                ["kubectl", "kustomize", str(tmp_path / "deploy/kubernetes/custom")],
                text=True,
            )
        )
    )
    app = next(
        item
        for item in resources
        if item["kind"] == "Deployment" and item["metadata"]["name"] == "immich-memories"
    )
    container = app["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}
    assert "IMMICH_MEMORIES_TIER" not in env
    assert env["IMMICH_MEMORIES_DEPLOYMENT_TIER"]["value"] == tier
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert app["metadata"]["namespace"] == "immich-memories"
    if tier != "basic":
        deployments = [item for item in resources if item["kind"] == "Deployment"]
        assert len(deployments) == 3
        assert env["IMMICH_MEMORIES_DEPLOYMENT_CAPTION_URL"]["value"] == "http://captioner:8092/v1"
        assert all(item["metadata"]["namespace"] == "immich-memories" for item in deployments)
        fetch = next(
            item
            for item in app["spec"]["template"]["spec"]["initContainers"]
            if item["name"] == "fetch-models"
        )
        assert fetch["command"] == ["immich-memories", "models", "fetch", "--detectors", "--laya"]
        init_env = {item["name"]: item["value"] for item in fetch["env"]}
        assert (
            init_env["IMMICH_MEMORIES_EDITORIAL__LAYA_CHECKPOINT"]
            == env["IMMICH_MEMORIES_EDITORIAL__LAYA_CHECKPOINT"]["value"]
        )
        assert init_env["IMMICH_MEMORIES_EDITORIAL__LAYA_CHECKPOINT"].startswith("/models/")
        assert {mount["mountPath"] for mount in fetch["volumeMounts"]} >= {
            "/models",
            "/home/immich/.immich-memories",
        }
        assert fetch["envFrom"] == [{"secretRef": {"name": "immich-memories-secrets"}}]

    if tier == "full":
        assert env["IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED"]["value"] == "true"
        reader = next(
            item
            for item in resources
            if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "immich-memories-reader"
        )
        assert reader["data"] == {
            "url": "http://reader.example.lan:9999/v1",
            "model": "served-model",
        }
    policy = next(
        item
        for item in resources
        if item["kind"] == "NetworkPolicy" and item["metadata"]["name"] == "immich-memories"
    )
    ports = {port["port"] for rule in policy["spec"]["egress"] for port in rule.get("ports", [])}
    assert 2283 in ports
    if tier == "full":
        assert 9999 in ports


def test_template_sync_cli_rejects_drift_after_a_shipped_file_changes(tmp_path):
    import sys

    snapshot = json.loads((ROOT / "docs-site/src/components/SetupBuilder/sources.json").read_text())
    files = {
        "base": "docker-compose.yml",
        "gpu": "docker-compose.gpu.yml",
        "full": "docker-compose.full.yml",
        "cuda": "docker-compose.cuda.yml",
        "worker": "docker-compose.gpu-worker.yml",
        "postgres": "docker-compose.postgres.yml",
    }
    for key, name in files.items():
        (tmp_path / name).write_text(yaml.safe_dump(snapshot[key]))
    output = tmp_path / "public-templates.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/sync_setup_templates.py"),
        "--source-root",
        str(tmp_path),
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True)
    subprocess.run([*command, "--check"], check=True)
    base = yaml.safe_load((tmp_path / "docker-compose.yml").read_text())
    base["services"]["immich-memories"]["image"] = "app:another-release"
    (tmp_path / "docker-compose.yml").write_text(yaml.safe_dump(base))
    stale = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert stale.returncode != 0
    assert "run make docs-setup" in stale.stderr


@pytest.mark.parametrize("platform", ["linux", "synology", "mac", "kubernetes"])
def test_current_templates_refuse_an_older_image_version(platform):
    result = _build(platform=platform, version="0.103.0")
    assert result["error"] == "These setup files require the docs build version 1.2.3."
    assert not result["files"]


def test_kubernetes_fast_path_exposes_private_ui_after_readiness():
    result = _build(platform="kubernetes")
    commands = result["commands"]
    assert "kubectl port-forward -n immich-memories svc/immich-memories 8080:80" in commands
    assert commands.index("immich-memories capabilities") < commands.index("kubectl port-forward")
    assert "Open http://localhost:8080" in commands


def test_setup_template_check_does_not_install_application_extras():
    # WHY: app dependency installation mutates the runner and is outside a docs-only check.
    result = subprocess.run(
        ["make", "docs-setup-check", "ENSURE_DEV_COMMAND=exit 81"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
