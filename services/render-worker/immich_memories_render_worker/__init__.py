"""Render a selected memory on a separate worker."""

import os

# The worker may import model dependencies before the app; telemetry is never authorized.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
