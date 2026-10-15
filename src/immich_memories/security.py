"""Security utilities for input validation and sanitization."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Control characters for sanitizing filenames
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Field names that hold a secret, wherever they appear in the config tree.
CREDENTIAL_FIELD_NAMES = frozenset(
    {"api_key", "caption_api_key", "password", "client_secret", "trigger_token", "worker_token"}
)
# Fixed on purpose: a fingerprint must map one key to one value across runs.
_FINGERPRINT_SALT = b"immich-memories/credential-fingerprint/v1"


def credential_fingerprint(secret: str) -> str:
    """A stable identity for a credential that can be stored or compared without the secret.

    Cache keys and job records hold this, never the key. scrypt, not a bare SHA-256:
    a leaked record must not be a cheap guessing oracle for a short or reused key.
    About 40 ms per call, paid once per run or job submission.
    """
    return hashlib.scrypt(secret.encode(), salt=_FINGERPRINT_SALT, n=2**14, r=8, p=1).hex()


def create_private_directory(path: Path) -> None:
    """Create missing directories at 0700, preserving existing ancestors' permissions.

    Path.mkdir(parents=True) uses the process umask for intermediate directories,
    even when its leaf requests 0700. Cached library data needs private parents too.
    """
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except FileNotFoundError:
        create_private_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)


def write_secret_file(path: Path, text: str) -> None:
    """Write a file that only its owner can read, from the moment it exists.

    `open("w")`/`write_text` create with the process umask -- 0644 on a normal
    system -- so narrowing the file afterwards with chmod leaves the secret
    world-readable in between. On a shared box or a NAS that window is the whole
    exposure, and it is invisible after the fact because the file looks correct
    by the time anyone inspects it. Creating at 0600 and renaming into place also
    means a crash mid-write cannot leave a truncated secret behind.
    """
    create_private_directory(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(temp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _assert_private(path: Path) -> None:
    """Refuse a path someone else could have prepared for us."""
    info = path.lstat()
    owned = info.st_uid == os.getuid()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or not owned:
        raise RuntimeError(f"{path} is not a private directory")
    if stat.S_IMODE(info.st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError(f"{path} is not a private directory (group/other access)")


def _tighten_own_directory(path: Path) -> None:
    """Narrow a real directory this user owns to 0700; touch nothing else.

    A volume remount can widen runtime scratch (Kubernetes `fsGroupChangePolicy: Always`
    makes it 2770), and scratch holds only throwaway files, so the app takes the access
    back itself. Tightening never widens anything. The directory is opened without following
    a symlink and checked on the descriptor, so a swapped-in link or another user's
    directory is left alone for `_assert_private` to refuse.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        if os.fstat(fd).st_uid == os.getuid():
            os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def private_temp_dir(name: str) -> Path:
    """A scratch directory under the runtime temp dir that only this user can enter.

    `tempfile.gettempdir()` is shared and world-writable, so a fixed path under
    it is a name another user can claim first -- as a symlink we then write
    through, since `ffmpeg -y` follows one, or as a directory they can read.
    Scoping by uid and refusing anything we do not own closes both.

    `lstat` rather than `stat`: the question is what the path itself is, and a
    symlink to a directory we own would answer "directory" through `stat`.
    """
    root = Path(tempfile.gettempdir()) / f"immich-memories-{os.getuid()}"
    target = root / name
    root.mkdir(mode=0o700, exist_ok=True)
    _assert_private(root)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_private(target)
    return target


@contextlib.contextmanager
def runtime_scratch(directory: Path) -> Iterator[Path]:
    """Keep Python and subprocess scratch on configured storage for a process lifetime.

    Enter at CLI/service startup, before launching threads or models. Setting the
    environment alone misses Python's cached tempdir; setting tempdir alone misses
    model and media subprocesses. An unusable mount must never fall back to /tmp.
    Nested CLI/web lifetimes restore the outer choice when they close.

    The process works in a folder of its own inside `<directory>/scratch`, and each start
    first sweeps the folders that processes killed mid-run left behind (`process_scratch`).
    """
    from immich_memories.process_scratch import owned_scratch, sweep_stale_scratch

    scratch = directory.expanduser().absolute() / "scratch"
    try:
        create_private_directory(scratch)
        _tighten_own_directory(scratch)
        _assert_private(scratch)
        # Verify writes now: tempfile's own directory search would silently fall back.
        with tempfile.TemporaryFile(dir=scratch):
            pass
    except OSError as error:
        raise OSError(
            error.errno, "Cannot use runtime scratch storage; check the configured volume."
        ) from None
    except RuntimeError:
        raise RuntimeError("Runtime scratch storage must be a private directory.") from None
    sweep_stale_scratch(scratch, directory.expanduser().absolute())
    previous = tempfile.tempdir
    environment = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
    try:
        with owned_scratch(scratch) as own:
            tempfile.tempdir = str(own)
            os.environ.update(dict.fromkeys(environment, str(own)))
            yield scratch
    finally:
        tempfile.tempdir = previous
        for key, value in environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _collect_model_secrets(value: BaseModel, secrets: set[str], pending: list[object]) -> None:
    for field_name in type(value).model_fields:
        field_value = getattr(value, field_name)
        if field_name in CREDENTIAL_FIELD_NAMES:
            if isinstance(field_value, str) and field_value:
                secrets.add(field_value)
        else:
            pending.append(field_value)


def configured_secret_values(config: BaseModel) -> tuple[str, ...]:
    """Return configured credentials and secret-bearing notification URLs."""
    secrets: set[str] = set()
    pending: list[object] = [config]
    while pending:
        value = pending.pop()
        if isinstance(value, BaseModel):
            _collect_model_secrets(value, secrets, pending)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)

    notifications = getattr(config, "notifications", None)
    for url in getattr(notifications, "urls", ()):
        if isinstance(url, str) and url:
            secrets.add(url)
    return tuple(sorted(secrets, key=len, reverse=True))


def validate_path(
    path: Path | str,
    must_exist: bool = False,
    allowed_extensions: set[str] | None = None,
) -> Path:
    """Resolve a file path and optionally check existence / extension.

    Args:
        path: The path to validate.
        must_exist: If True, raise error if path doesn't exist.
        allowed_extensions: Set of allowed extensions (e.g., {'.mp4', '.mov'}).

    Returns:
        Resolved Path object.

    Raises:
        ValueError: If path fails validation.
    """
    if isinstance(path, str):
        path = Path(path)

    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Cannot resolve path: {e}") from e

    if allowed_extensions is not None:
        ext = resolved.suffix.lower()
        if ext not in allowed_extensions:
            raise ValueError(f"Extension '{ext}' not in allowed list: {allowed_extensions}")

    if must_exist and not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")

    return resolved


def validate_video_path(path: Path | str, must_exist: bool = True) -> Path:
    """Validate a video file path."""
    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        ".mpeg",
        ".mpg",
        ".3gp",
        ".ts",
    }
    return validate_path(path, must_exist=must_exist, allowed_extensions=VIDEO_EXTENSIONS)


def validate_audio_path(path: Path | str, must_exist: bool = True) -> Path:
    """Validate an audio file path."""
    AUDIO_EXTENSIONS = {
        ".mp3",
        ".m4a",
        ".wav",
        ".flac",
        ".ogg",
        ".aac",
        ".wma",
        ".opus",
        ".aiff",
    }
    return validate_path(path, must_exist=must_exist, allowed_extensions=AUDIO_EXTENSIONS)


def validate_image_path(path: Path | str, must_exist: bool = True) -> Path:
    """Validate an image file path."""
    IMAGE_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".tiff",
        ".tif",
        ".heic",
        ".heif",
    }
    return validate_path(path, must_exist=must_exist, allowed_extensions=IMAGE_EXTENSIONS)


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize a filename for safe filesystem use.

    Args:
        filename: The filename to sanitize.
        max_length: Maximum length for the filename.

    Returns:
        Sanitized filename.
    """
    sanitized = _CONTROL_CHARS.sub("", filename).replace("/", "_").replace("\\", "_").strip(" .")

    # Truncate if too long (preserve extension if possible)
    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        if len(ext) < max_length:
            name = name[: max_length - len(ext)]
            sanitized = name + ext
        else:
            sanitized = sanitized[:max_length]

    if not sanitized:
        sanitized = "unnamed"

    return sanitized


def sanitize_error_message(msg: str) -> str:
    """Strip API keys and auth tokens from error messages before displaying to users.

    Prevents accidental exposure of credentials in UI error displays or logs.
    """
    msg = re.sub(r"x-api-key['\"]?\s*[:=]\s*['\"]?\S+", "x-api-key=***", msg, flags=re.IGNORECASE)
    msg = re.sub(r"Bearer\s+\S+", "Bearer ***", msg, flags=re.IGNORECASE)
    msg = re.sub(r"api[_-]?key['\"]?\s*[:=]\s*['\"]?\S+", "api_key=***", msg, flags=re.IGNORECASE)
    return msg


def sanitize_client_error(exc: BaseException, client: object | None = None) -> str:
    """The error as a log line, with token shapes stripped and the client's own key masked.

    The key can appear verbatim in a transport error (a URL, an echoed header) without any
    of the shapes `sanitize_error_message` recognises, so the client's key is masked too.
    """
    message = sanitize_error_message(str(exc))
    api_key = getattr(client, "api_key", None)
    if isinstance(api_key, str) and api_key:
        message = message.replace(api_key, "***")
    return message
