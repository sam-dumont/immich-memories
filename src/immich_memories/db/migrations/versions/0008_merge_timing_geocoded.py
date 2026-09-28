"""Join the run timing and geocoded places revisions, which both grew from 0006_banks.

Revision ID: 0008_merge_timing_geocoded
Revises: 0007_timing, 0007_geocoded_places
"""

revision = "0008_merge_timing_geocoded"
down_revision = ("0007_timing", "0007_geocoded_places")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
