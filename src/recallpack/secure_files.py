from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import os
from pathlib import Path
import stat


class SecureFileError(ValueError):
    pass


def canonical_relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise SecureFileError("invalid_seed_generation_path: path must be text")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise SecureFileError(
            "invalid_seed_generation_path: path must be ASCII"
        ) from None
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        raise SecureFileError(
            "invalid_seed_generation_path: path must be canonical repository-relative POSIX text"
        )
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise SecureFileError(
            "invalid_seed_generation_path: dot and empty components are forbidden"
        )
    return parts


@contextmanager
def open_canonical_root(repository_root: Path) -> Iterator[int]:
    root = Path(repository_root)
    if not root.is_absolute():
        raise SecureFileError(
            "invalid_seed_generation_path: repository root must be absolute"
        )
    try:
        original = os.stat(root, follow_symlinks=False)
        if stat.S_ISLNK(original.st_mode):
            raise SecureFileError(
                "invalid_seed_generation_path: repository root symlink is forbidden"
            )
        if not stat.S_ISDIR(original.st_mode):
            raise SecureFileError(
                "invalid_seed_generation_path: repository root must be a directory"
            )
        canonical = root.resolve(strict=True)
    except OSError as exc:
        raise SecureFileError(
            "invalid_seed_generation_path: repository root does not exist"
        ) from exc
    if not canonical.is_dir():
        raise SecureFileError(
            "invalid_seed_generation_path: repository root must be a directory"
        )
    flags = _directory_flags()
    try:
        descriptor = os.open(canonical, flags)
    except OSError as exc:
        raise SecureFileError(
            "invalid_seed_generation_path: repository root cannot be opened safely"
        ) from exc
    try:
        before = os.stat(canonical, follow_symlinks=False)
        opened = os.fstat(descriptor)
        if (
            not _same_identity(original, before)
            or not stat.S_ISDIR(opened.st_mode)
            or not _same_identity(before, opened)
        ):
            raise SecureFileError(
                "invalid_seed_generation_path: repository root changed during open"
            )
        yield descriptor
    finally:
        os.close(descriptor)


def open_directory_beneath(root_fd: int, parts: Sequence[str]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                expected = os.stat(part, dir_fd=current, follow_symlinks=False)
                child = os.open(part, _directory_flags(), dir_fd=current)
            except OSError as exc:
                raise SecureFileError(
                    "invalid_seed_generation_path: directory component is missing, unsafe, or not permitted"
                ) from exc
            opened = os.fstat(child)
            if not stat.S_ISDIR(opened.st_mode) or not _same_identity(expected, opened):
                os.close(child)
                raise SecureFileError(
                    "invalid_seed_generation_path: directory component changed during open"
                )
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def stable_read_beneath(root_fd: int, relative_path: str) -> bytes:
    parts = canonical_relative_parts(relative_path)
    parent = open_directory_beneath(root_fd, parts[:-1])
    try:
        return stable_read_at(parent, parts[-1])
    finally:
        os.close(parent)


def stable_read_at(
    parent_fd: int,
    name: str,
    *,
    expected_stat: os.stat_result | None = None,
) -> bytes:
    try:
        descriptor = os.open(name, _file_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise SecureFileError(
            "invalid_seed_generation_path: input file is missing, symlinked, or not permitted"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if expected_stat is not None and not _same_identity(expected_stat, before):
            raise SecureFileError(
                "invalid_seed_generation_path: input identity changed during open"
            )
        if not stat.S_ISREG(before.st_mode):
            raise SecureFileError(
                "invalid_seed_generation_path: input must be a regular file"
            )
        if before.st_nlink != 1:
            raise SecureFileError(
                "invalid_seed_generation_path: hardlinked input is forbidden"
            )
        payload = bytearray()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise SecureFileError(
                    "invalid_seed_generation_path: input changed while reading"
                )
            payload.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SecureFileError(
                "invalid_seed_generation_path: input grew while reading"
            )
        after = os.fstat(descriptor)
        if _stable_signature(before) != _stable_signature(after):
            raise SecureFileError(
                "invalid_seed_generation_path: input changed while reading"
            )
        return bytes(payload)
    finally:
        os.close(descriptor)


def walk_python_tree(root_fd: int, relative_root: str) -> list[tuple[str, bytes]]:
    root_parts = canonical_relative_parts(relative_root)
    directory_fd = open_directory_beneath(root_fd, root_parts)
    try:
        return _walk_python_directory(
            directory_fd,
            prefix="/".join(root_parts),
        )
    finally:
        os.close(directory_fd)


def _walk_python_directory(directory_fd: int, *, prefix: str) -> list[tuple[str, bytes]]:
    before = os.fstat(directory_fd)
    try:
        entries = list(os.scandir(directory_fd))
        entries.sort(key=lambda entry: entry.name.encode("utf-8"))
    except (OSError, UnicodeEncodeError) as exc:
        raise SecureFileError(
            "invalid_seed_generation_path: code directory cannot be enumerated safely"
        ) from exc
    files: list[tuple[str, bytes]] = []
    for entry in entries:
        name = entry.name
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise SecureFileError(
                "invalid_seed_generation_path: code entry changed during enumeration"
            ) from exc
        if stat.S_ISLNK(entry_stat.st_mode):
            kind = "directory" if entry.is_dir(follow_symlinks=True) else "file"
            raise SecureFileError(
                f"invalid_seed_generation_path: symlinked {kind} in frozen root"
            )
        relative = f"{prefix}/{name}"
        if stat.S_ISDIR(entry_stat.st_mode):
            if name == "__pycache__":
                raise SecureFileError(
                    "invalid_seed_generation_path: __pycache__ in frozen root"
                )
            try:
                child = os.open(name, _directory_flags(), dir_fd=directory_fd)
            except OSError as exc:
                raise SecureFileError(
                    "invalid_seed_generation_path: code directory changed during open"
                ) from exc
            try:
                if not _same_identity(entry_stat, os.fstat(child)):
                    raise SecureFileError(
                        "invalid_seed_generation_path: code directory identity changed"
                    )
                files.extend(_walk_python_directory(child, prefix=relative))
            finally:
                os.close(child)
            continue
        if name.endswith(".pyc"):
            raise SecureFileError(
                "invalid_seed_generation_path: bytecode in frozen root"
            )
        if name.endswith(".py"):
            if not stat.S_ISREG(entry_stat.st_mode):
                raise SecureFileError(
                    "invalid_seed_generation_path: Python code must be a regular file"
                )
            files.append(
                (
                    relative,
                    stable_read_at(directory_fd, name, expected_stat=entry_stat),
                )
            )
    after = os.fstat(directory_fd)
    if _directory_signature(before) != _directory_signature(after):
        raise SecureFileError(
            "invalid_seed_generation_path: code directory changed during enumeration"
        )
    return files


def _directory_flags() -> int:
    return os.O_RDONLY | _required_flag("O_DIRECTORY") | _required_flag("O_NOFOLLOW")


def _file_flags() -> int:
    return os.O_RDONLY | _required_flag("O_NOFOLLOW")


def _required_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise SecureFileError(
            f"invalid_seed_generation_path: platform lacks required {name} support"
        )
    return value


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _stable_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
