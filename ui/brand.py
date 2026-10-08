"""Shared ONE LINK brand proportions, adapted to the RawBaker Qt editor."""
from pathlib import Path
import platform
from html import escape
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFontDatabase, QIcon, QDesktopServices, QPalette
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
                             QGridLayout, QDialog, QStackedWidget, QTextBrowser, QScrollArea, QApplication)
from version import APP_NAME, VERSION_TUPLE, COMPANY, YEAR, IS_BETA

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
CHANNEL = 'https://www.youtube.com/@unknown8563'
DISCORD = 'https://discord.gg/fmwEzmCzPz'
SUBTITLE = 'Photo processing & design'


def translator(parent):
    return getattr(parent,'tr_text',lambda ko,en:en if getattr(parent,'_lang_key','ko')=='en' else ko)


def load_brand_fonts():
    for name in ('Rajdhani-Bold.ttf', 'Pretendard-Regular.ttf', 'Pretendard-Medium.ttf', 'Pretendard-Bold.ttf'):
        QFontDatabase.addApplicationFont(str(ASSETS/'fonts'/name))


def platform_label():
    return f'{platform.system()} {platform.release()} · {platform.machine()}'


def icon(size):
    label = QLabel()
    label.setPixmap(QIcon(str(ASSETS/'icon.ico')).pixmap(size,size))
    label.setFixedSize(size,size)
    return label


def brand_header(parent, callback):
    load_brand_fonts()
    bar=QWidget(parent);bar.setObjectName('brandHeader');bar.setFixedHeight(44)
    row=QHBoxLayout(bar);row.setContentsMargins(14,0,14,0);row.setSpacing(9)
    row.addWidget(icon(36))
    title=QLabel('Raw<span style="color:#D35400">Baker</span>');title.setObjectName('brandWordmark')
    title.setStyleSheet('font-family:Rajdhani;font-size:29px;font-weight:700;')
    row.addWidget(title)
    subtitle=QLabel(SUBTITLE);subtitle.setStyleSheet('font-size:11px;');row.addWidget(subtitle)
    row.addStretch()
    credit=QLabel(f'{APP_NAME} · {COMPANY}');credit.setStyleSheet('font-size:11px;');row.addWidget(credit)
    button=QPushButton('?');button.setFixedSize(24,24);button.setObjectName('brandAboutButton')
    caption=translator(parent)('RawBaker 정보','About RawBaker')
    button.setAccessibleName(caption);button.setToolTip(caption)
    button.setStyleSheet('QPushButton {border:1px solid #777;border-radius:12px;padding:0;} QPushButton:hover {border-color:#D35400;color:#D35400;}')
    button.clicked.connect(callback);row.addWidget(button)
    return bar


class BrandAbout(QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.setWindowTitle(translator(parent)('RawBaker 정보','About RawBaker'))
        self.setMinimumWidth(390)
        self.setModal(True)
        tr=translator(parent)
        dark=parent.palette().color(QPalette.Window).lightness()<128
        bg='#252527' if dark else '#ffffff';fg='#eeeeee' if dark else '#242424'
        muted='#b6b6bd' if dark else '#686868';line='#48484c' if dark else '#dddddd'
        accent='#ed8d4e' if dark else '#bd4b00'
        self.setStyleSheet(f'QDialog,QWidget#aboutPage {{background:{bg};color:{fg};font-family:Pretendard;font-size:12px;}} QLabel {{background:transparent;color:{fg};font-family:Pretendard;font-size:12px;}} QPushButton {{font-family:Pretendard;font-size:12px;padding:7px 18px;}} QPushButton[primary="true"] {{background:{accent};color:{"#111111" if dark else "white"};border:0;border-radius:5px;}} QPushButton[primary="true"]:hover {{background:#D35400;color:white;}}')
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.pages=QStackedWidget();outer.addWidget(self.pages)
        page=QWidget();page.setObjectName('aboutPage');self.pages.addWidget(page)
        layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        banner=QWidget();banner.setObjectName('aboutBanner');banner.setFixedHeight(90)
        banner.setStyleSheet('QWidget#aboutBanner {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #C0390B,stop:1 #D35400);border-top-left-radius:15px;border-top-right-radius:15px;}')
        br=QHBoxLayout(banner);br.setContentsMargins(22,10,22,10);br.setSpacing(11);br.addWidget(icon(60))
        titles=QVBoxLayout();title=QLabel(APP_NAME);title.setStyleSheet('color:white;font-family:Rajdhani;font-size:29px;font-weight:700;')
        titles.addWidget(title);sub=QLabel(SUBTITLE);sub.setStyleSheet('color:#ffe2d4;font-size:11px;');titles.addWidget(sub);br.addLayout(titles);br.addStretch();layout.addWidget(banner)
        body=QWidget();grid=QGridLayout(body);grid.setContentsMargins(25,18,25,16);grid.setHorizontalSpacing(12);grid.setVerticalSpacing(11)
        rows=[(tr('프로젝트','Project'),APP_NAME),(tr('제작','Creator'),COMPANY),(tr('연도','Year'),YEAR),
              (tr('버전','Version'),'.'.join(map(str,VERSION_TUPLE[:3]))),(tr('유튜브','YouTube'),None),
              (tr('디스코드','Discord'),None),(tr('엔진','Engine'),'rawpy · Pillow · OpenCV'),(tr('플랫폼','Platform'),platform_label())]
        for i,(caption,value) in enumerate(rows):
            label=QLabel(caption);label.setFixedWidth(70);label.setStyleSheet(f'color:{muted};font-size:11px;');grid.addWidget(label,i,0,Qt.AlignTop)
            if value is None:
                field=QPushButton('▶ @unknown8563 ↗');field.setAccessibleName(tr('공식 유튜브 채널 열기','Open official YouTube channel'))
                field.setStyleSheet(f'color:{accent};background:transparent;border:0;padding:0;text-align:left;')
                if i == 5:
                    field.setText(tr('Discord 커뮤니티 참여 ↗','Join Discord community ↗'))
                    field.setAccessibleName(field.text())
                    field.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(DISCORD)))
                else:
                    field.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(CHANNEL)))
            else:
                field=QLabel(value);field.setWordWrap(True)
                if i<2:field.setStyleSheet(f'color:{accent};font-weight:600;')
                if i==3:
                    field.setObjectName('aboutVersion')
                    if IS_BETA:field.setText(escape(value)+' <span style="color:'+accent+';font-size:10px">PREVIEW</span>')
            grid.addWidget(field,i,1)
        desc=QLabel(tr('사진 변환·보정·레이어 디자인을 한곳에서.','Photo conversion, editing and layer design in one place.'));desc.setWordWrap(True);desc.setStyleSheet('font-size:11px;');grid.addWidget(desc,len(rows),0,1,2)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
        content=QWidget();content_layout=QVBoxLayout(content);content_layout.setContentsMargins(0,0,0,0);content_layout.setAlignment(Qt.AlignTop);content_layout.addWidget(body)
        from ui.app_update import UpdatePanel
        self.updates=UpdatePanel(content,tr);content_layout.addWidget(self.updates)
        scroll.setWidget(content);layout.addWidget(scroll,1)
        footer=QWidget();footer.setStyleSheet(f'QWidget {{border-top:1px solid {line};}} QPushButton {{border-top:0;}}')
        fr=QHBoxLayout(footer);fr.setContentsMargins(20,12,20,12)
        self.licenses=QPushButton(tr('글꼴 라이선스','Font licenses'));self.licenses.clicked.connect(self.show_licenses);fr.addWidget(self.licenses);fr.addStretch()
        ok=QPushButton(tr('확인','OK'));ok.setProperty('primary',True);ok.clicked.connect(self.accept);ok.setDefault(True);fr.addWidget(ok);layout.addWidget(footer)
        license_page=QWidget();ll=QVBoxLayout(license_page)
        self.license_text=QTextBrowser();self.license_text.setOpenExternalLinks(False);ll.addWidget(self.license_text)
        back=QPushButton(tr('앱 정보로 돌아가기','Back to About'));back.clicked.connect(lambda:self.pages.setCurrentIndex(0));ll.addWidget(back)
        self.pages.addWidget(license_page)
        screen=QApplication.primaryScreen().availableGeometry()
        self.resize(420,min(620,screen.height()-60))
        self.setMinimumHeight(min(320,screen.height()-60))

    def show_licenses(self):
        texts=[]
        for name in ('Pretendard-OFL.txt','Rajdhani-OFL.txt','OFL.txt'):
            texts.append(name+'\n\n'+(ASSETS/'fonts'/name).read_text(encoding='utf8'))
        self.license_text.setPlainText('\n\n'.join(texts));self.pages.setCurrentIndex(1)
