import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The sdist ships these trees, and the wheel is built from the sdist.
SHIPPED = ("src", "tests")


def test_no_tracked_symlink_points_into_a_shipped_tree():
    # Hatchling walks the tree with symlinks followed and skips any directory whose inode it
    # has already seen. A link from docs-site/ into src/ is walked first (alphabetically), so
    # the real directory is skipped and silently missing from the sdist and wheel (#1976).
    staged = subprocess.run(
        ["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    links = [line.split("\t", 1)[1] for line in staged.splitlines() if line.startswith("120000")]
    offending = []
    for link in links:
        target = (ROOT / link).resolve()
        if any(target.is_relative_to(ROOT / tree) for tree in SHIPPED):
            offending.append(f"{link} -> {target.relative_to(ROOT)}")
    assert offending == []
