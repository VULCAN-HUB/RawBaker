"""Project file/recovery UI, kept separate from the legacy conversion window."""
from copy import deepcopy
from pathlib import Path
import shutil
from uuid import uuid4

from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer, QStandardPaths, QLockFile, QEventLoop, Qt
from PyQt5.QtWidgets import QPushButton, QLabel, QWidget, QHBoxLayout, QMessageBox, QFileDialog, QProgressDialog, QShortcut
from PyQt5.QtGui import QKeySequence

from core.project import Project, ProjectError, digest
from core.project_session import ProjectSession
from core.project_store import load_project, save_project
from core.safe_output import is_protected


class ProjectTask(QThread):
    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function, self.result, self.error = function, None, None

    def run(self):
        try:
            self.result = self.function()
        except Exception as error:
            self.error = error


class ProjectController(QObject):
    def __init__(self, window, storage_root=None, offer_recovery=True):
        super().__init__(window)
        self.window = window
        self.base = Path(storage_root or (Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / "project-sessions"))
        self.base.mkdir(parents=True, exist_ok=True)
        self.session = None
        self.path = None
        self.token = None
        self.lease = None
        self.retired = []
        self.task = None
        self.busy = False
        self.applying = False
        self._saved = self.snapshot()
        self._checkpoint = None
        self._retry_snapshot = None
        self._checkpoint_error = None
        self._setup_bar()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(2500)
        if offer_recovery:
            QTimer.singleShot(0, self.offer_recovery)

    def _setup_bar(self):
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 0, 4, 0)
        self.buttons = []
        for label, callback in (("프로젝트 열기", self.open_dialog), ("저장", self.save),
                                ("다른 이름으로 저장", lambda: self.save(save_as=True))):
            button = QPushButton(label)
            button.setStyleSheet(self.window._outline_btn_style())
            button.setMinimumHeight(28)
            button.clicked.connect(lambda checked=False, cb=callback: cb())
            layout.addWidget(button)
            self.buttons.append(button)
        self.label = QLabel("새 작업")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color:#BBBBBB; padding:0 8px;")
        layout.addWidget(self.label, 1)
        self.window.centralWidget().layout().insertWidget(1, bar)
        for key, callback in (("Ctrl+O", self.open_dialog), ("Ctrl+S", self.save),
                              ("Ctrl+Shift+S", lambda: self.save(save_as=True))):
            shortcut = QShortcut(QKeySequence(key), self.window)
            shortcut.activated.connect(callback)

    def snapshot(self):
        rows = []
        for item in self.window._items:
            if not hasattr(item, "project_key"):
                item.project_key = str(uuid4())
            rows.append(dict(key=item.project_key, path=item.path, adjustments=deepcopy(item.adjustments)))
        options = self.window.options.get_settings()
        options["auto_bright"] = self.window.options.get_auto_bright()
        return {"rows": rows, "options": options}

    @property
    def dirty(self):
        current = self.snapshot()
        return bool(current["rows"] or self.session) and current != self._saved

    def _title(self):
        name = self.path.name if self.path else "새 작업"
        suffix = " · 저장하지 않은 변경" if self.dirty else ""
        if self._checkpoint_error:
            suffix += " · 복구 저장 실패: 저장 버튼으로 재시도"
        self.label.setText(name + suffix)
        self.window.setWindowTitle(f"RawBaker — {name}{' *' if self.dirty else ''}")

    def _new_session(self):
        root = self.base / uuid4().hex
        root.mkdir()
        lease = QLockFile(str(root / "active.lock"))
        if not lease.tryLock(0):
            raise ProjectError("작업 폴더를 잠글 수 없습니다.")
        self.lease = lease
        self.session = ProjectSession(Project(root))

    def _synchronize(self, snapshot):
        self.session.synchronize(snapshot["rows"], snapshot["options"])

    def _run(self, function, title):
        """Modal UI boundary; disk work runs on a worker, never on the GUI thread."""
        if self.busy:
            return False, None
        self.busy = True
        dialog = QProgressDialog(title, "", 0, 0, self.window)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
        dialog.setMinimumDuration(0)
        task = ProjectTask(function, self)
        self.task = task
        loop = QEventLoop()
        task.finished.connect(loop.quit)
        dialog.show()
        task.start()
        loop.exec_()
        task.wait()
        dialog.close()
        self.busy = False
        self.task = None
        result, error = task.result, task.error
        task.deleteLater()
        if error is not None:
            QMessageBox.warning(self.window, "프로젝트 작업 실패", str(error))
            return False, None
        return True, result

    def poll(self):
        if self.busy or self.applying or self.window._converting:
            return
        self._title()
        snapshot = self.snapshot()
        # Plain batch conversion does not copy the whole input into a project.
        edited = any(row["adjustments"] for row in snapshot["rows"])
        if snapshot["rows"] and self._saved is not None:
            edited = edited or snapshot["options"] != self._saved["options"]
        if not (self.session or edited) or not self.dirty:
            return
        if snapshot == self._checkpoint or snapshot == self._retry_snapshot:
            return
        if self.session is None:
            self._new_session()
        self.busy = True
        task = ProjectTask(lambda: self._synchronize(snapshot), self)
        self.task = task
        def completed():
            task.wait()
            self.busy = False
            self.task = None
            if task.error:
                self._retry_snapshot = snapshot
                self._checkpoint_error = str(task.error)
                self.label.setText(f"자동 복구 저장 실패: {task.error} · 저장 버튼으로 재시도")
            else:
                self._checkpoint = snapshot
                self._retry_snapshot = None
                self._checkpoint_error = None
                self._title()
            task.deleteLater()
        task.finished.connect(completed)
        task.start()

    def save(self, save_as=False, destination=None):
        if self.busy or self.window._converting:
            QMessageBox.information(self.window, "작업 진행 중", "진행 중인 저장 또는 변환이 끝난 뒤 저장하세요.")
            return False
        target = Path(destination) if destination else (None if save_as else self.path)
        chosen = target is None or destination is not None
        if target is None:
            name, _ = QFileDialog.getSaveFileName(self.window, "프로젝트 저장", str(self.path or "새 작업.rbproj"), "RawBaker 프로젝트 (*.rbproj)")
            if not name:
                return False
            target = Path(name)
        if target.suffix.lower() != ".rbproj":
            target = target.with_name(target.name + ".rbproj")
        snapshot = self.snapshot()
        if self.session is None:
            self._new_session()
        def work():
            if is_protected(target, [r["path"] for r in snapshot["rows"]]):
                raise ProjectError("입력 사진에 프로젝트를 덮어쓸 수 없습니다.")
            self._synchronize(snapshot)
            # Save As's file chooser confirms replacement. Ordinary Save must
            # retain the token from opening, never adopt an external edit.
            expected = self.token if self.path and target.resolve() == self.path.resolve() else None
            if chosen and (not self.path or target.resolve() != self.path.resolve()) and target.exists():
                expected = digest(target)
            return save_project(self.session.project, target, expected_token=expected)
        ok, token = self._run(work, "원본과 편집 내용을 저장하는 중…")
        if ok:
            self.path, self.token = target, token
            self._saved = snapshot
            self._checkpoint = snapshot
            self._retry_snapshot = None
            self._checkpoint_error = None
            self._title()
        return ok

    def confirm_leave(self):
        if self.busy:
            QMessageBox.information(self.window, "저장 중", "프로젝트 저장이 끝난 뒤 다시 시도하세요.")
            return False
        if not self.dirty:
            return True
        answer = QMessageBox.question(self.window, "저장하지 않은 작업", "변경한 작업을 프로젝트로 저장할까요?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Cancel:
            return False
        return self.save() if answer == QMessageBox.Save else True

    def _retire(self):
        if self.session:
            self.retired.append((self.session.project.root, self.lease))
        self.session = self.lease = None

    def reset(self):
        self._retire()
        self.path = self.token = None
        self._saved = self.snapshot()
        self._checkpoint = self._retry_snapshot = None
        self._checkpoint_error = None
        self._title()

    def open_dialog(self):
        if self.busy or self.window._converting:
            QMessageBox.information(self.window, "작업 진행 중", "진행 중인 저장 또는 변환이 끝난 뒤 프로젝트를 여세요.")
            return
        name, _ = QFileDialog.getOpenFileName(self.window, "프로젝트 열기", "", "RawBaker 프로젝트 (*.rbproj)")
        if name:
            self.open_path(name)

    def open_path(self, source):
        if self.busy or self.window._converting or not self.confirm_leave():
            return False
        root = self.base / uuid4().hex
        def work():
            project, token = load_project(source, root)
            session = ProjectSession(project)
            return session, token, session.rows()
        ok, result = self._run(work, "프로젝트 원본과 편집 내용을 확인하는 중…")
        if not ok:
            self._clean(root)
            return False
        lease = QLockFile(str(root / "active.lock"))
        if not lease.tryLock(0):
            QMessageBox.warning(self.window, "프로젝트 열기", "작업 폴더를 잠글 수 없습니다.")
            return False
        session, token, rows = result
        self._retire()
        self.session, self.lease = session, lease
        self.path, self.token = Path(source), token
        self._apply(rows)
        self._saved = self.snapshot()
        self._checkpoint = self._saved
        self._retry_snapshot = None
        self._checkpoint_error = None
        self._title()
        return True

    def _apply(self, rows):
        from ui.drop_area import FileItem
        self.applying = True
        try:
            self.window._reset(project_switch=True)
            self.window.file_list.blockSignals(True)
            try:
                for row in rows:
                    item = FileItem(row["path"], self.window._lang)
                    item.project_key = row["key"]
                    item.adjustments = row["adjustments"]
                    item._refresh_display()
                    self.window._items.append(item)
                    self.window.file_list.addItem(item)
            finally:
                self.window.file_list.blockSignals(False)
            options = self.session.project.state["ui"]["options"]
            self.window.options.apply_settings(options)
            self.window.options.set_auto_bright(options.get("auto_bright", True))
            # Never export into a disposable session's view directory.
            self.window.options.same_src_cb.setChecked(False)
            self.window.options.folder_edit.clear()
            self.window._update_status_label()
            from ui.main_window import ThumbnailLoader
            paths = [item.path for item in self.window._items if item.needs_thumbnail()]
            if paths:
                loader = ThumbnailLoader(paths)
                loader.thumb_ready.connect(self.window._on_thumb_ready)
                self.window._retain(loader)
                loader.start()
        finally:
            self.applying = False

    def offer_recovery(self):
        if self.busy or self.window._items or self.session:
            return
        for root in sorted(self.base.iterdir()):
            import re
            if (root.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", root.name)
                    or not root.is_dir() or not (root / "recovery.json").exists()):
                continue
            lease = QLockFile(str(root / "active.lock"))
            if not lease.tryLock(0):
                continue
            answer = QMessageBox.question(self.window, "이전 작업 복구", "종료 전에 남은 작업이 있습니다. 복구할까요?\n아니요를 선택해도 다음 실행까지 보관됩니다.",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                lease.unlock()
                continue
            def work():
                session = ProjectSession(Project.recover(root))
                return session, session.rows()
            ok, result = self._run(work, "이전 작업을 복구하는 중…")
            if not ok:
                lease.unlock()
                continue
            self.session, rows = result
            self.lease = lease
            self.path = self.token = None  # Recovery always asks for a save path.
            self._apply(rows)
            self._saved = None
            self._checkpoint = self.snapshot()
            self._title()
            return

    def export_folder(self, folder):
        managed = any(self.base.resolve() in Path(i.path).resolve().parents for i in self.window._items)
        if not managed:
            return folder
        if folder and self.base.resolve() != Path(folder).resolve() and self.base.resolve() not in Path(folder).resolve().parents:
            return folder
        selected = QFileDialog.getExistingDirectory(self.window, "변환 결과를 저장할 폴더 선택")
        if not selected:
            return None
        if Path(selected).resolve() == self.base.resolve() or self.base.resolve() in Path(selected).resolve().parents:
            QMessageBox.warning(self.window, "출력 폴더", "임시 작업 폴더 밖의 저장 위치를 선택하세요.")
            return None
        self.window.options.same_src_cb.setChecked(False)
        self.window.options.folder_edit.setText(selected)
        return selected

    def _clean(self, root):
        # Only UUID session directories directly inside our own storage root.
        import re
        root = Path(root)
        if root.resolve().parent == self.base.resolve() and re.fullmatch(r"[0-9a-f]{32}", root.name) and not root.is_symlink():
            shutil.rmtree(root, ignore_errors=True)

    def shutdown(self):
        self.timer.stop()
        self._retire()
        for root, lease in self.retired:
            if lease:
                lease.unlock()
            self._clean(root)
        self.retired.clear()
