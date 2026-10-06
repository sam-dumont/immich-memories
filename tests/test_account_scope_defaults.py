"""An AccountScope built with no arguments is an empty, per-instance scope.

The defaults were once a shared mappingproxy, which Python 3.11's dataclasses refuse at
import time; this module fails to import there if that ever comes back.
"""

from immich_memories.free_text.account_scope import AccountScope


def test_a_scope_with_no_accounts_sees_no_owner_and_no_face() -> None:
    scope = AccountScope()

    assert dict(scope.picture_accounts) == {}
    assert dict(scope.face_accounts) == {}
