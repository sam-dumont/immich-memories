"""Version constants import without OpenCV: an image build stage that seeds models has no
libGL/libxcb, and importing a head's version must not load the GUI build of cv2 there."""

import subprocess
import sys

import pytest

LIGHT_MODULES = (
    "immich_memories.model_bundle",
    "immich_memories.store.asset_annotations",
    "immich_memories.analysis.preparation.heads",
    "immich_memories.analysis.preparation.remote_facts",
    "immich_memories.analysis.facts.obstruction",
)


@pytest.mark.parametrize("module", LIGHT_MODULES)
def test_the_module_imports_where_opencv_cannot_load(module):
    # WHY: a child interpreter, so blocking cv2 there cannot touch this process's imports.
    probe = (
        "import sys; sys.modules['cv2'] = None; "
        f"import {module}; "
        "assert 'cv2' not in sys.modules or sys.modules['cv2'] is None"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False
    )

    assert result.returncode == 0, result.stderr[-2000:]
