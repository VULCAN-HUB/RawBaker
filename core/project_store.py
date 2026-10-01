"""Versioned .rbproj packages. Streaming assets; validated before publication."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Callable
import zipfile

from core.project import Project, ProjectError, decode, digest, encode, validate, migrate

MAX_STATE = 16 * 1024 * 1024
MAX_BYTES = 64 * 1024 ** 3
MAX_ENTRIES = 10002


class SaveConflict(ProjectError):
    pass


class SaveCancelled(ProjectError):
    pass


def _cancel(cancelled):
    if cancelled and cancelled():
        raise SaveCancelled("저장을 취소했습니다.")


def _inspect(archive: zipfile.ZipFile) -> dict:
    infos = archive.infolist()
    names = [i.filename for i in infos]
    if len(names) > MAX_ENTRIES or len(names) != len(set(names)):
        raise ProjectError("중복 파일 또는 과도한 파일 수입니다.")
    if sum(i.file_size for i in infos) > MAX_BYTES:
        raise ProjectError("프로젝트 크기 제한을 초과했습니다.")
    for info in infos:
        if (info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16)
                or info.file_size / max(1, info.compress_size) > 200):
            raise ProjectError("지원하지 않는 압축 항목입니다.")
    if "manifest.json" not in names or "state/project.json" not in names:
        raise ProjectError("프로젝트 정보가 없습니다.")
    for name in ("manifest.json", "state/project.json"):
        if archive.getinfo(name).file_size > MAX_STATE:
            raise ProjectError("프로젝트 정보가 너무 큽니다.")
    manifest = decode(archive.read("manifest.json"))
    raw_state = archive.read("state/project.json")
    original = decode(raw_state)
    state = migrate(original)
    validate(state)
    if manifest != {"schema_version": original["schema_version"], "project_id": state["id"],
                    "state_sha256": hashlib.sha256(raw_state).hexdigest()}:
        raise ProjectError("프로젝트 정보의 무결성 검사 실패입니다.")
    expected = {"manifest.json", "state/project.json"} | {f"assets/{key}" for key in state["assets"]}
    if set(names) != expected:
        raise ProjectError("누락되거나 허용되지 않은 패키지 경로입니다.")
    for key, asset in state["assets"].items():
        if archive.getinfo(f"assets/{key}").file_size != asset["size"]:
            raise ProjectError("원본 자산 크기가 다릅니다.")
    return state


def _verify_blob(archive, key, output=None, cancelled=None):
    hasher = hashlib.sha256()
    with archive.open(f"assets/{key}") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            _cancel(cancelled)
            hasher.update(chunk)
            if output is not None:
                output.write(chunk)
    if hasher.hexdigest() != key:
        raise ProjectError("원본 자산 해시가 다릅니다.")


def save_project(project: Project, target: str | Path, *, expected_token: str | None = None,
                 cancelled: Callable[[], bool] | None = None) -> str:
    """None requires a new destination; existing files require their load/save token.

    An exclusive adjacent lock serializes cooperating processes. A crash may leave
    the lock: report a conflict rather than automatically deleting another lock.
    """
    target = Path(target).resolve()
    if target == project.root.resolve() or project.root.resolve() in target.parents:
        raise ProjectError("프로젝트 파일은 작업 원본 폴더 밖에 저장하세요.")
    lock = target.with_name(target.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise SaveConflict("다른 저장 작업이 진행 중이거나 이전 잠금이 남아 있습니다.") from error
    os.close(lock_fd)
    temporary = None
    try:
        def check_token():
            current = digest(target) if target.exists() else None
            if current != expected_token:
                raise SaveConflict("파일이 다른 곳에서 변경됐습니다. 별도 이름으로 저장하세요.")

        check_token()
        state = deepcopy(project.state)
        validate(state)
        raw_state = encode(state)
        if len(raw_state) > MAX_STATE or len(state["assets"]) + 2 > MAX_ENTRIES:
            raise ProjectError("프로젝트 정보 제한을 초과했습니다.")
        if sum(a["size"] for a in state["assets"].values()) + len(raw_state) > MAX_BYTES:
            raise ProjectError("프로젝트 크기 제한을 초과했습니다.")
        _cancel(cancelled)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".rbproj-", suffix=".tmp")
        with os.fdopen(fd, "w+b") as stream:
            # Already compressed photos: STORE avoids costly recompression and
            # makes writer output obey the same expansion checks as the reader.
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("manifest.json", encode(dict(schema_version=state["schema_version"], project_id=state["id"],
                                      state_sha256=hashlib.sha256(raw_state).hexdigest())))
                archive.writestr("state/project.json", raw_state)
                for key, asset in state["assets"].items():
                    hasher = hashlib.sha256()
                    size = 0
                    with (project.root / "assets" / key).open("rb") as source, archive.open(
                            f"assets/{key}", "w", force_zip64=True) as output:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            _cancel(cancelled)
                            output.write(chunk)
                            hasher.update(chunk)
                            size += len(chunk)
                    if hasher.hexdigest() != key or size != asset["size"]:
                        raise ProjectError("저장 중 원본이 없거나 변경되었습니다.")
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as archive:
            verified = _inspect(archive)
            for key in verified["assets"]:
                _verify_blob(archive, key, cancelled=cancelled)
        token = digest(Path(temporary))
        _cancel(cancelled)
        check_token()
        os.replace(temporary, target)
        return token
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def load_project(source: str | Path, workspace: str | Path) -> tuple[Project, str]:
    """Load into a new directory only. Never extract supplied archive path names."""
    source, workspace = Path(source), Path(workspace)
    if workspace.exists():
        raise ProjectError("새 작업 폴더가 필요합니다.")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=workspace.parent, prefix=".rbload-"))
    try:
        with source.open("rb") as stream:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                state = _inspect(archive)
                project = Project(temporary, state)
                for key in state["assets"]:
                    with (temporary / "assets" / key).open("wb") as output:
                        _verify_blob(archive, key, output)
                project.checkpoint()
            stream.seek(0)
            after = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                after.update(chunk)
            if after.digest() != hasher.digest():
                raise SaveConflict("불러오는 중 프로젝트 파일이 변경되었습니다.")
        os.rename(temporary, workspace)
        return Project(workspace, state), hasher.hexdigest()
    except (zipfile.BadZipFile, EOFError, OSError) as error:
        raise ProjectError(f"프로젝트를 열 수 없습니다: {error}") from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
