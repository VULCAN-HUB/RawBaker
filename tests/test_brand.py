import os,subprocess,sys
import pytest


@pytest.mark.parametrize('language',['ko','en'])
def test_brand_identity_fonts_and_licenses(tmp_path,language):
    script=r'''
from pathlib import Path
import sys,PyQt5
from PyQt5.QtCore import QCoreApplication,QSettings
QCoreApplication.addLibraryPath(str(Path(PyQt5.__file__).parent/'Qt5/plugins'))
from PyQt5.QtWidgets import QApplication,QLabel,QPushButton
from PyQt5.QtGui import QFontDatabase,QDesktopServices
from ui.editor_window import EditorWindow
from ui.brand import BrandAbout,CHANNEL,DISCORD
from version import VERSION_TUPLE
from core.project import encode
app=QApplication([]);root=Path(sys.argv[1])
QSettings.setDefaultFormat(QSettings.IniFormat);QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(root/'settings'))
w=EditorWindow(lang_key=sys.argv[2],storage_root=root/'sessions',offer_recovery=False)
w.resize(1024,768);w.show();app.processEvents();before=encode(w.project.state)
assert 'Rajdhani' in QFontDatabase().families() and 'Pretendard' in QFontDatabase().families()
assert w.brand_header.height()==44
button=w.brand_header.findChild(QPushButton,'brandAboutButton');assert button.size().width()==24 and button.accessibleName()
about=BrandAbout(w);about.show();app.processEvents()
assert '.'.join(map(str,VERSION_TUPLE[:2])) in about.findChild(QLabel,'aboutVersion').text()
assert about.width()<=w.width() and about.height()<=768
opened=[];QDesktopServices.openUrl=lambda url:opened.append(url.toString())
next(b for b in about.findChildren(QPushButton) if '@unknown8563' in b.text()).click();assert opened==[CHANNEL]
next(b for b in about.findChildren(QPushButton) if "Discord" in b.text()).click();assert opened==[CHANNEL,DISCORD]
assert about.updates.controller.state=="idle"
assert about.updates.action.isEnabled()
about.licenses.click();assert about.pages.currentIndex()==1
text=about.license_text.toPlainText();assert 'SIL OPEN FONT LICENSE' in text and 'Rajdhani' in text and 'Pretendard' in text
about.pages.setCurrentIndex(0);about.grab().save(str(root/'about.png'));w.grab().save(str(root/'editor.png'))
assert encode(w.project.state)==before
about.close();w.debounce.stop();w.saved=encode(w.project.state);w.close()
'''
    run=subprocess.run([sys.executable,'-c',script,str(tmp_path),language],capture_output=True,text=True,encoding='utf8',env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONIOENCODING='utf-8'),timeout=45)
    assert run.returncode==0,run.stdout+run.stderr
