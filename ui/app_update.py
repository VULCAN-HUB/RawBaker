"""Non-blocking, user-initiated update UI shared by both RawBaker workspaces."""
import platform
import sys
import threading
from urllib.error import HTTPError, URLError
from PyQt5.QtCore import QObject, pyqtSignal, QStandardPaths, QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar, QApplication
from core import app_update as service
from version import VERSION_TUPLE, IS_BETA


def current_version():
    return '.'.join(map(str, VERSION_TUPLE[:3])) + ('-editor-preview' if IS_BETA else '')


def build_target():
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine().lower(), 'unknown')
    # Only the existing Windows ZIP distribution has a defined package contract.
    return ('windows' if sys.platform == 'win32' else sys.platform, arch,
            'portable-zip' if getattr(sys, 'frozen', False) and sys.platform == 'win32' else 'source')


class UpdateController(QObject):
    changed = pyqtSignal()
    completed = pyqtSignal(str, object)
    received = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state, self.reason = 'idle', ''
        self.package = self.path = None
        self.amount = (0, 0)
        self.cancel_event = threading.Event()
        self.completed.connect(self._complete)
        self.received.connect(self._progress)

    def _complete(self, state, value):
        self.state = state
        if state == 'available':
            self.package = value
        elif state == 'ready':
            self.path = value
        else:
            self.reason = value or ''
        self.changed.emit()

    def _progress(self, count, total):
        self.amount = (count, total)
        self.changed.emit()

    def _run(self, fn, success):
        def worker():
            try:
                result = fn()
                self.completed.emit(success if result is not None else 'current', result)
            except service.Cancelled:
                self.completed.emit('available', self.package)
            except service.UpdateError as exc:
                reason = str(exc)
                self.completed.emit('unavailable' if reason in ('package', 'empty', 'feed_limit') else 'error', reason)
            except HTTPError as exc:
                self.completed.emit('error', 'rate' if exc.code in (403, 429) else 'http')
            except (URLError, TimeoutError, ConnectionError, OSError):
                self.completed.emit('error', 'network')
            except Exception:
                self.completed.emit('error', 'metadata')
        threading.Thread(target=worker, daemon=True).start()

    def check(self):
        if self.state in ('checking', 'downloading'):
            return
        self.state, self.reason = 'checking', ''
        self.package = self.path = None
        self.changed.emit()
        self._run(lambda: service.check(current_version(), IS_BETA, build_target()), 'available')

    def download(self):
        if self.state != 'available' or self.package is None:
            return
        self.cancel_event.clear()
        self.state, self.amount = 'downloading', (0, self.package.size)
        self.changed.emit()
        from pathlib import Path
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)) / 'VULCAN' / 'RawBaker' / 'updates'
        self._run(lambda: service.download(self.package, cache, self.cancel_event, self.received.emit), 'ready')

    def cancel(self):
        if self.state == 'downloading':
            self.cancel_event.set()

    def apply(self):
        # No executable replacement until an OS/package installer is validated.
        return False


class UpdatePanel(QWidget):
    def __init__(self, parent, tr, controller=None):
        super().__init__(parent)
        self.tr_text = tr
        app = QApplication.instance()
        if controller is None:
            if not hasattr(app, '_rawbaker_updates'):
                app._rawbaker_updates = UpdateController(app)
                app.aboutToQuit.connect(app._rawbaker_updates.cancel)
            controller = app._rawbaker_updates
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 4, 25, 14)
        layout.setAlignment(Qt.AlignTop)
        title = QLabel(tr('앱 업데이트', 'App updates'))
        title.setStyleSheet('font-weight:600;color:#D35400;')
        layout.addWidget(title)
        self.version = QLabel(tr('현재 버전: ', 'Current version: ') + current_version() + (' · PREVIEW' if IS_BETA else ''))
        self.version.setWordWrap(True)
        layout.addWidget(self.version)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.action = QPushButton()
        self.action.setObjectName('updateAction')
        self.action.clicked.connect(self.act)
        layout.addWidget(self.action)
        controller.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        c, tr = self.controller, self.tr_text
        messages = {
            'idle': ('확인을 누르면 공개 배포 버전을 조회합니다.', 'Check public releases when you choose.'),
            'checking': ('새 버전을 확인하고 있습니다…', 'Checking for updates…'),
            'current': ('현재 채널에 더 새로운 공개 버전이 없습니다.', 'No newer public release in this channel.'),
            'available': ('새 버전: ', 'New version: '),
            'downloading': ('업데이트를 다운로드하고 있습니다…', 'Downloading update…'),
            'ready': ('파일 검증 완료. 다운로드 가능 / 자동 적용 준비 중. 작업을 저장하고 앱을 종료한 뒤 ZIP을 새 폴더에 풀어 실행하세요. 해시 검증은 전자서명이 아닙니다.', 'File verified. Download supported / automatic installation pending. Save your work and close the app, then extract the ZIP to a new folder. A checksum is not a digital signature.'),
            'unavailable': ('이 배포에는 현재 환경용 업데이트 패키지가 준비되지 않았습니다. 앱은 계속 사용할 수 있습니다.', 'An update package for this environment is not available. You can keep using the app.'),
            'error': ('업데이트를 확인하지 못했습니다. 다시 시도하세요.', 'Could not check updates. Please retry.'),
        }
        errors = {
            'network': ('네트워크 연결 또는 저장 공간을 확인한 뒤 다시 시도하세요.', 'Check your connection and available storage, then retry.'),
            'rate': ('조회 제한에 도달했습니다. 잠시 후 다시 시도하세요.', 'Release service rate limit reached. Try again later.'),
            'hash': ('파일 검증에 실패하여 다운로드 파일을 폐기했습니다. 다시 확인해 주세요.', 'File verification failed. The download was discarded. Please check again.'),
            'metadata': ('배포 정보 형식이 올바르지 않습니다. 나중에 다시 확인하세요.', 'Invalid release metadata. Please check again later.'),
            'origin': ('허용되지 않은 다운로드 주소입니다.', 'The download address is not allowed.'),
            'http': ('공개 배포 서버에 접근할 수 없습니다. 나중에 다시 시도하세요.', 'Public release service unavailable. Please retry later.'),
            'empty': ('공개된 업데이트가 아직 없습니다.', 'No public updates are available yet.'),
            'feed_limit': ('전체 배포 목록을 확인하지 못했습니다. 나중에 다시 시도하세요.', 'Could not verify the complete release list. Please retry later.'),
        }
        text = tr(*messages[c.state])
        if c.state in ('error', 'unavailable') and c.reason in errors:
            text = tr(*errors[c.reason])
        if c.state == 'available' and c.package:
            text += c.package.version + (' · PREVIEW' if c.package.preview else '')
            text += tr('\nZIP 다운로드 지원 · 자동 적용 준비 중', '\nZIP download supported · automatic installation pending')
        self.status.setText(text)
        self.progress.setVisible(c.state == 'downloading')
        self.progress.setValue(int(100 * c.amount[0] / c.amount[1]) if c.amount[1] else 0)
        label = {'available': ('업데이트 다운로드', 'Download update'), 'downloading': ('다운로드 취소', 'Cancel download'),
                 'ready': ('검증된 파일 폴더 열기', 'Open verified download folder')}.get(c.state, ('업데이트 확인', 'Check for updates'))
        self.action.setText(tr(*label))
        self.action.setEnabled(c.state != 'checking')

    def act(self):
        c = self.controller
        if c.state == 'available':
            c.download()
        elif c.state == 'downloading':
            c.cancel()
        elif c.state == 'ready' and c.path:
            # Open a directory only. Never execute or extract a downloaded asset.
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(c.path.parent))):
                c._complete('error', 'folder')
        else:
            c.check()
