"""Adapt a legacy file list to portable project state without depending on Qt."""
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil

from core.project import Project, ProjectError, validate


class ProjectSession:
    def __init__(self, project: Project):
        self.project = project

    def synchronize(self, rows: list[dict], options: dict):
        project = self.project
        if any(p["engine_version"] != "legacy-v1" for p in project.state["photos"].values()):
            raise ProjectError("새 편집 프로젝트는 RawBaker Studio에서 열어주세요.")
        # Work on a detached state. Failed imports may leave unreferenced blobs,
        # but must not change the last recoverable edit state.
        staged = Project(project.root, project.state)
        order = []
        for row in rows:
            key = row["key"]
            if key not in staged.state["photos"]:
                imported = staged.import_photo(row["path"])
                staged.state["photos"][key] = staged.state["photos"].pop(imported)
                staged.state["ui"]["photo_order"].remove(imported)
                staged._undo.clear()
            if staged.state["photos"][key]["adjustments"] != row["adjustments"]:
                staged.set_adjustments(key, row["adjustments"])
                staged._undo.clear()
            order.append(key)
        retained = set(order)
        for doc in staged.state["documents"].values():
            retained.update(layer.get("photo_id", layer.get("data", {}).get("photo_id")) for layer in doc["layers"])
        staged.state["photos"] = {k: v for k, v in staged.state["photos"].items() if k in retained}
        used_assets = {p["asset_id"] for p in staged.state["photos"].values()}
        staged.state["assets"] = {k: v for k, v in staged.state["assets"].items() if k in used_assets}
        staged.state["ui"] = {"photo_order": order, "options": deepcopy(options),
                              "photo_names": {row["key"]: Path(row["path"]).name for row in rows}}
        staged.state["revision"] += 1
        validate(staged.state)
        staged.checkpoint(verify_assets=False)
        self.project = staged

    def rows(self) -> list[dict]:
        """Create named read copies; legacy decoders select by file extension."""
        result = []
        project = self.project
        if any(p["engine_version"] != "legacy-v1" for p in project.state["photos"].values()) or any(
                "kind" in layer for doc in project.state["documents"].values() for layer in doc["layers"]):
            raise ProjectError("새 편집 프로젝트는 RawBaker Studio에서 열어주세요.")
        for key in project.state["ui"]["photo_order"]:
            photo = project.state["photos"][key]
            asset_id = photo["asset_id"]
            asset = project.state["assets"][asset_id]
            original_name = project.state["ui"].get("photo_names", {}).get(key, asset["name"])
            name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', original_name).strip(" .")
            if not name or len(name) > 200:
                raise ProjectError("원본 파일 이름을 복원할 수 없습니다.")
            # Photo IDs are untrusted JSON strings: never use them as paths.
            import hashlib
            folder = project.root / "views" / hashlib.sha256(key.encode()).hexdigest()
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / name
            if not destination.exists():
                source = project.root / "assets" / asset_id
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
            result.append(dict(key=key, path=str(destination), adjustments=deepcopy(photo["adjustments"])))
        return result
