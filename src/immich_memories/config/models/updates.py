"""Whether this install asks GitHub, once a day, if a newer release is out."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Named here so the docs, the code and the tests cannot drift apart.
RELEASES_HOST = "api.github.com"


class UpdatesConfig(BaseModel):
    """The daily release check; the on-demand check needs no setting."""

    check_daily: bool = Field(
        default=False,
        description=(
            f"Ask {RELEASES_HOST} once a day whether a newer release is out, and say so in the "
            "web app and the run log. The request is an anonymous list of public releases: "
            "no version, install id or setting goes with it"
        ),
    )
