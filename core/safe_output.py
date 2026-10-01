"""Publish complete output files without exposing partial writes or changing inputs."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import tempfile
import threading
from typing import Iterable, Callable, BinaryIO

_publish_lock = threading.Lock()


class ProtectedInputError(ValueError):
    pass


def is_protected(path: str | Path, inputs: Iterable[str | Path]) -> bool:
    target = os.path.normcase(os.path.realpath(path))
    for source in inputs:
        if target == os.path.normcase(os.path.realpath(source)):
            return True
        try:
            if os.path.samefile(path, source):
                return True
        except FileNotFoundError:
            pass
    return False


def write_output(data: bytes | Callable[[BinaryIO], None], destination: str | Path, *, mode: str = "rename",
                 protected_inputs: Iterable[str | Path] = (), protected_hashes: Iterable[str] = (), max_path: int = 260) -> str | None:
    """Write beside the target, then publish. Unsupported filesystems fail closed.

    data may be bytes or a producer writing to the owned temporary stream.
    Producer failures/cancellation never publish a partial file.

    Windows rename() and POSIX link() publish without clobbering other writers;
    replace() publishes overwrites without first truncating the target.
    The lock serializes in-app writers. External malicious path substitution is
    outside this local desktop application's concurrency guarantee.
    """
    if mode not in {"rename", "overwrite", "skip"}:
        raise ValueError(f"지원하지 않는 충돌 처리: {mode}")
    destination = Path(destination)
    inputs = tuple(protected_inputs)
    hashes = set(protected_hashes)
    def protected(target):
        if is_protected(target, inputs):
            return True
        if hashes and Path(target).is_file():
            hasher = hashlib.sha256()
            with open(target, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
            return hasher.hexdigest() in hashes
        return False
    if len(str(destination)) > max_path:
        raise ValueError("출력 경로가 너무 깁니다.")
    if mode == "overwrite" and protected(destination):
        raise ProtectedInputError("출력 대상이 작업 원본입니다. 다른 이름이나 폴더를 선택하세요.")
    if mode == "skip" and os.path.lexists(destination):
        return None

    fd, temporary = tempfile.mkstemp(prefix=".rawbaker-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if callable(data):data(stream)
            else:stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        with _publish_lock:
            if mode == "overwrite":
                if protected(destination):
                    raise ProtectedInputError("출력 대상이 작업 원본입니다. 덮어쓸 수 없습니다.")
                os.replace(temporary, destination)
                return str(destination)
            counter = 0
            while True:
                target = destination if counter == 0 else destination.with_name(
                    f"{destination.stem}_{counter}{destination.suffix}")
                if len(str(target)) > max_path:
                    raise ValueError("출력 경로가 너무 깁니다.")
                if is_protected(target, inputs):
                    if mode == "skip":
                        return None
                    counter += 1
                    continue
                try:
                    if os.name == "nt":
                        os.rename(temporary, target)
                    else:
                        os.link(temporary, target)
                    return str(target)
                except FileExistsError:
                    if mode == "skip":
                        return None
                    counter += 1
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
