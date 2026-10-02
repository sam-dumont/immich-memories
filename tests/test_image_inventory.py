"""An image inventory must not quietly drop shipped third-party packages."""

import pytest
from scripts.image_inventory import requirements


def test_local_distributions_are_recorded_but_not_queried_on_pypi():
    installed = {"immich-memories": "1.0", "torch": "2.13.0+cpu", "fastapi": "0.135.2"}
    assert requirements(installed) == "fastapi==0.135.2\ntorch==2.13.0+cpu\n"


@pytest.mark.parametrize("installed", [{}, {"immich-memories": "1.0"}])
def test_empty_dependency_inventory_is_not_an_all_clear(installed):
    with pytest.raises(ValueError, match="empty"):
        requirements(installed)


@pytest.mark.parametrize("installed", [{"bad\nname": "1"}, {"package": "1\n--index-url=x"}])
def test_requirements_cannot_contain_installer_options(installed):
    with pytest.raises(ValueError, match="invalid"):
        requirements(installed)
