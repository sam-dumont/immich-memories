from immich_memories.config import Config
from immich_memories.preflight import CheckStatus, run_preflight_checks
from immich_memories.preflight_sign_in import check_sign_in


def _basic(password: str) -> Config:
    return Config(
        auth={"enabled": True, "provider": "basic", "username": "op", "password": password}
    )


def test_a_short_basic_password_is_a_preflight_warning():
    result = check_sign_in(_basic("short-pw"))

    assert result.status is CheckStatus.WARNING
    assert "12 characters" in result.message


def test_a_long_basic_password_passes():
    assert check_sign_in(_basic("a-much-longer-password")).status is CheckStatus.OK


def test_auth_off_skips_the_check():
    assert check_sign_in(Config()).status is CheckStatus.SKIPPED


def test_preflight_runs_the_sign_in_check():
    names = [result.name for result in run_preflight_checks(_basic("short-pw"))]

    assert "Sign-in" in names
