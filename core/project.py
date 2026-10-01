"""Qt-independent project state and an owned, recoverable working directory."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

SCHEMA_VERSION = 12


def migrate(state: dict) -> dict:
    """Read version 1 without touching the original package."""
    state = deepcopy(state)
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 1:
        state["schema_version"] = 2
        state["ui"] = {"photo_order": list(state.get("photos", {})), "options": {}}
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 2:
        state["schema_version"] = 3
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 3:
        state["schema_version"] = 4
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 4:
        state["schema_version"] = 5
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 5:
        state["schema_version"] = 6
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 6:
        state["schema_version"] = 7
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 7:
        state["schema_version"] = 8
    if type(state) is dict and type(state.get("schema_version")) is int and state["schema_version"] == 8:
        state["schema_version"] = 9
    if type(state) is dict and type(state.get('schema_version')) is int and state['schema_version']==9:
        state['schema_version']=10
    if type(state) is dict and type(state.get('schema_version')) is int and state['schema_version']==10:
        state['schema_version']=11
    if type(state) is dict and type(state.get('schema_version')) is int and state['schema_version']==11:
        state['schema_version']=12
    return state


class ProjectError(ValueError):
    pass


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def encode(state: dict) -> bytes:
    return json.dumps(state, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProjectError("중복 JSON 키입니다.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ProjectError("잘못된 숫자입니다.")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError(f"프로젝트 JSON 오류: {error}") from error


def validate(state: dict) -> None:
    try:
        if (type(state) is not dict or type(state.get("schema_version")) is not int
                or state.get("schema_version") != SCHEMA_VERSION):
            raise ProjectError("지원하지 않는 프로젝트 버전입니다.")
        if set(state) != {"schema_version", "id", "revision", "assets", "photos", "documents", "ui"}:
            raise ProjectError("프로젝트 필드가 올바르지 않습니다.")
        if not isinstance(state["id"], str) or not state["id"]:
            raise ProjectError("프로젝트 ID가 없습니다.")
        if type(state["revision"]) is not int or state["revision"] < 0:
            raise ProjectError("잘못된 revision입니다.")
        for collection in ("assets", "photos", "documents"):
            if type(state[collection]) is not dict:
                raise ProjectError("잘못된 객체 목록입니다.")
        ui = state["ui"]
        if (type(ui) is not dict or set(ui) not in ({"photo_order", "options"}, {"photo_order", "options", "photo_names"})
                or type(ui["options"]) is not dict):
            raise ProjectError("잘못된 화면 상태입니다.")
        studio_options = ui["options"].get("studio_export")
        if studio_options is not None:
            from core.edit_spec import number
            if type(studio_options) is not dict or set(studio_options) != {"format", "quality", "bits", "dpi", "metadata", "max_side", "collision", "suffix"}:
                raise ProjectError("잘못된 Studio 출력 설정입니다.")
            if studio_options["format"] not in ("PNG", "JPEG", "TIFF", "WEBP") or studio_options["bits"] not in (8, 16):
                raise ProjectError("지원하지 않는 출력 형식입니다.")
            if studio_options["metadata"] not in ("keep", "remove_gps", "remove_all") or studio_options["collision"] not in ("rename", "overwrite", "skip"):
                raise ProjectError("잘못된 출력 정책입니다.")
            number(studio_options["quality"], 1, 100)
            number(studio_options["dpi"], 1, 9600)
            if studio_options["max_side"] is not None: number(studio_options["max_side"], 1, 30000)
            if type(studio_options["suffix"]) is not str or len(studio_options["suffix"]) > 200:
                raise ProjectError("잘못된 출력 접미사입니다.")
        names = ui.get("photo_names", {})
        if type(names) is not dict or any(k not in state["photos"] or type(v) is not str or not v for k, v in names.items()):
            raise ProjectError("잘못된 사진 이름입니다.")
        order = ui["photo_order"]
        if (type(order) is not list or any(type(p) is not str or p not in state["photos"] for p in order)
                or len(set(order)) != len(order)):
            raise ProjectError("잘못된 사진 순서입니다.")
        for key, asset in state["assets"].items():
            if not re.fullmatch(r"[0-9a-f]{64}", key):
                raise ProjectError("잘못된 자산 ID입니다.")
            if set(asset) != {"name", "size"} or type(asset["size"]) is not int or asset["size"] < 0:
                raise ProjectError("잘못된 자산 정보입니다.")
            if not isinstance(asset["name"], str) or not asset["name"]:
                raise ProjectError("자산 이름이 없습니다.")
        for key, photo in state["photos"].items():
            if not isinstance(key, str) or not key or set(photo) != {"asset_id", "adjustments", "revision", "engine_version"}:
                raise ProjectError("잘못된 사진 버전입니다.")
            if photo["asset_id"] not in state["assets"]:
                raise ProjectError("사진의 원본이 없습니다.")
            if type(photo["revision"]) is not int or photo["revision"] < 0 or photo["engine_version"] not in ("legacy-v1", "linear-v1"):
                raise ProjectError("지원하지 않는 보정 버전입니다.")
            if type(photo["adjustments"]) is not dict:
                raise ProjectError("잘못된 보정값입니다.")
            if photo["engine_version"] == "linear-v1":
                from core.edit_spec import validate_edit
                validate_edit(photo["adjustments"])
            else:
                for value in photo["adjustments"].values():
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ProjectError("보정값은 유한한 숫자여야 합니다.")
        for key, document in state["documents"].items():
            if not isinstance(key, str) or not key or set(document) not in ({"width", "height", "layers"},{"width", "height", "layers", "groups"}):
                raise ProjectError("잘못된 문서입니다.")
            if any(type(document[n]) is not int or not 0 < document[n] <= 100000 for n in ("width", "height")):
                raise ProjectError("잘못된 캔버스 크기입니다.")
            if type(document["layers"]) is not list:
                raise ProjectError("잘못된 레이어 목록입니다.")
            from core.edit_spec import validate_layer
            ids = []
            for layer in document["layers"]:
                validate_layer(layer, state["photos"])
                if layer.get("kind")=="adjustment" and (layer["x"]!=0 or layer["y"]!=0 or layer["width"]!=document["width"] or layer["height"]!=document["height"]):
                    raise ProjectError("조정 레이어는 문서 전체 크기여야 합니다.")
                if "id" in layer:
                    ids.append(layer["id"])
            if len(ids) != len(set(ids)):
                raise ProjectError("중복 레이어 ID입니다.")
            from core.layer_groups import validate_groups
            validate_groups(document)
        encode(state)
    except (TypeError, KeyError, OverflowError, RecursionError, ValueError) as error:
        if isinstance(error, ProjectError):
            raise
        raise ProjectError("프로젝트 구조가 올바르지 않습니다.") from error


class Project:
    def __init__(self, root: str | Path, state: dict | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        self.state = migrate(state) if state is not None else dict(
            schema_version=SCHEMA_VERSION, id=str(uuid4()), revision=0, assets={}, photos={}, documents={},
            ui={"photo_order": [], "options": {}})
        validate(self.state)
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    def _change(self, state: dict):
        state["revision"] = self.state["revision"] + 1
        validate(state)
        self._bump_photos(state)
        self._undo.append(deepcopy(self.state))
        self._undo = self._undo[-50:]
        self._redo.clear()
        self.state = state

    def _bump_photos(self, state: dict):
        # Undo followed by a new edit must never reuse an old cache revision.
        for key, photo in state["photos"].items():
            if photo != self.state["photos"].get(key):
                photo["revision"] = state["revision"]

    def import_photo(self, source: str | Path, *, engine_version: str = "legacy-v1") -> str:
        source = Path(source)
        fd, temporary = tempfile.mkstemp(dir=self.root / "assets", prefix=".import-")
        try:
            hasher = hashlib.sha256()
            size = 0
            with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    output.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            asset_id = hasher.hexdigest()
            destination = self.root / "assets" / asset_id
            if destination.exists():
                if digest(destination) != asset_id:
                    raise ProjectError("작업 원본이 손상되었습니다.")
            else:
                os.replace(temporary, destination)
            state = deepcopy(self.state)
            state["assets"].setdefault(asset_id, {"name": source.name, "size": size})
            photo_id = str(uuid4())
            state["photos"][photo_id] = dict(asset_id=asset_id, adjustments={}, revision=0, engine_version=engine_version)
            state["ui"]["photo_order"].append(photo_id)
            self._change(state)
            return photo_id
        finally:
            Path(temporary).unlink(missing_ok=True)

    def set_adjustments(self, photo_id: str, adjustments: dict):
        state = deepcopy(self.state)
        state["photos"][photo_id]["adjustments"] = deepcopy(adjustments)
        state["photos"][photo_id]["revision"] += 1
        self._change(state)

    def duplicate_photo(self, photo_id: str) -> str:
        state = deepcopy(self.state)
        new_id = str(uuid4())
        state["photos"][new_id] = deepcopy(state["photos"][photo_id])
        if photo_id in state["ui"].get("photo_names", {}):
            state["ui"]["photo_names"][new_id] = state["ui"]["photo_names"][photo_id]
        state["ui"]["photo_order"].append(new_id)
        self._change(state)
        return new_id

    def add_document(self, width: int, height: int, photo_ids: list[str]) -> str:
        state = deepcopy(self.state)
        document_id = str(uuid4())
        state["documents"][document_id] = dict(width=width, height=height,
                                             layers=[dict(photo_id=p) for p in photo_ids])
        self._change(state)
        return document_id

    def _travel(self, source: list, destination: list) -> bool:
        if not source:
            return False
        destination.append(deepcopy(self.state))
        state = source.pop()
        state["revision"] = self.state["revision"] + 1
        self._bump_photos(state)
        self.state = state
        return True

    def undo(self) -> bool:
        return self._travel(self._undo, self._redo)

    def redo(self) -> bool:
        return self._travel(self._redo, self._undo)

    def verify_assets(self):
        validate(self.state)
        for key, asset in self.state["assets"].items():
            path = self.root / "assets" / key
            if not path.is_file() or path.stat().st_size != asset["size"] or digest(path) != key:
                raise ProjectError("원본 자산이 없거나 손상되었습니다.")

    def checkpoint(self, *, verify_assets: bool = True):
        if verify_assets:
            self.verify_assets()
        else:
            validate(self.state)
        data = encode(self.state)
        if len(data) > 16 * 1024 * 1024:
            raise ProjectError("복구 정보가 너무 큽니다.")
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".checkpoint-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.root / "recovery.json")
        finally:
            Path(name).unlink(missing_ok=True)

    @classmethod
    def recover(cls, root: str | Path) -> "Project":
        root = Path(root)
        path = root / "recovery.json"
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ProjectError("복구 정보가 너무 큽니다.")
        project = cls(root, decode(path.read_bytes()))
        project.verify_assets()
        return project
