"""Every laya-mlx install instruction names the tested version range, never a bare package.

The MLX threshold was calibrated on one laya-mlx; later releases were re-run on the public
calibration and held-out captions before the range was widened. A bare `laya-mlx` lets the next
major install unchecked, so the docs, the setup builder and the app's own messages pin it.
"""

import re
from pathlib import Path

from immich_memories.laya_checkpoints import LAYA_MLX_REQUIREMENT
from immich_memories.update_check import update_command

ROOT = Path(__file__).resolve().parents[1]
# An install line: pip/uv pip install or uv tool's --with, followed later by the package.
_INSTALL = re.compile(r"(pip install|--with)\b[^\n]*laya-mlx")


def _install_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if _INSTALL.search(line)]


def test_requirement_has_an_upper_bound():
    assert LAYA_MLX_REQUIREMENT.startswith("laya-mlx>=")
    assert ",<" in LAYA_MLX_REQUIREMENT


def test_docs_install_lines_pin_laya_mlx():
    pages = [
        *(ROOT / "docs-site" / "docs").rglob("*.md"),
        *(ROOT / "docs-site" / "src").rglob("*.ts"),
    ]
    lines = [(page, line) for page in pages for line in _install_lines(page.read_text())]
    assert lines, "no laya-mlx install line found: the pattern no longer matches the docs"
    bare = [
        f"{page.relative_to(ROOT)}: {line.strip()}"
        for page, line in lines
        if LAYA_MLX_REQUIREMENT not in line
    ]
    assert not bare, "\n".join(bare)


def test_update_command_pins_laya_mlx_on_a_mac():
    command = update_command("pip", "v1.0.0", platform="darwin")
    assert command is not None
    assert f'--with "{LAYA_MLX_REQUIREMENT}"' in command
