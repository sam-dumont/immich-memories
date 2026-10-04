"""The permissions this app needs, separate from authentication and delivery policy."""

from dataclasses import dataclass

READ_PERMISSIONS = (
    "user.read",
    "asset.read",
    "asset.statistics",
    "asset.view",
    "asset.download",
    "face.read",
    "person.read",
    "person.statistics",
    "album.read",
    "map.search",
)
UPLOAD_PERMISSIONS = (
    "asset.upload",
    "tag.create",
    "tag.asset",
    "album.create",
    "albumAsset.create",
)
DELETE_PERMISSION = "asset.delete"


class MissingReadPermissions(RuntimeError):
    """A key cannot read all source material required for a complete film."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__("API key lacks required read permissions: " + ", ".join(missing))


@dataclass(frozen=True)
class ApiKeyCapabilities:
    """Effective rights for one key; Immich's `all` grants every individual permission."""

    permissions: frozenset[str]

    @property
    def is_all(self) -> bool:
        return "all" in self.permissions

    def allows(self, permission: str) -> bool:
        """Whether Immich would allow this operation, including an unrestricted key."""
        return self.is_all or permission in self.permissions

    @property
    def missing_read(self) -> tuple[str, ...]:
        return tuple(permission for permission in READ_PERMISSIONS if not self.allows(permission))

    @property
    def missing_upload(self) -> tuple[str, ...]:
        return tuple(permission for permission in UPLOAD_PERMISSIONS if not self.allows(permission))

    def require_read(self) -> None:
        """Refuse an incomplete source read, naming every permission the owner must add."""
        if missing := self.missing_read:
            raise MissingReadPermissions(missing)
