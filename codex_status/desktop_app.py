import os
from pathlib import Path
import subprocess
import sys
import time
import re
from datetime import datetime, timezone, timedelta

from PySide6.QtCore import QObject, Signal, QSettings, QTimer, Qt, QSize, QUrl
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QAction, QImage, QFontMetrics, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QProgressBar,
    QSystemTrayIcon, QMenu, QFileDialog, QDialog, QLineEdit, QSlider,
)
from desktop_bridge import DesktopBridge
from account import read_account
from release_check import ReleaseCheck
from version import APP_VERSION, FIRMWARE_VERSION, version_tuple

ASSETS = (Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parent)/'assets'


class Events(QObject):
    ready = Signal()
    connection = Signal(str, str)
    busy = Signal(bool)
    updated = Signal(dict)
    devices = Signal(list)
    scanned = Signal()
    error = Signal(str, str)
    scheduled = Signal(float)
    firmware = Signal(str)
    upgrade_progress = Signal(int, str)
    upgrade_done = Signal(bool, str)
    profile_applied = Signal()
    tasks = Signal(dict)
    account = Signal(object)
    paired = Signal(str,str)
    contact = Signal(float)
    stopped = Signal()


def account_name():
    account=read_account()
    return account['name'] if account else '未登录'


def app_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#132d29'))
    painter.drawRoundedRect(4, 4, 120, 120, 30, 30)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor('#80e8ba'), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(29, 29, 70, 70, 42 * 16, 276 * 16)
    painter.setPen(QPen(QColor('#e1fff0'), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(68, 64, 87, 64)
    painter.end()
    return QIcon(pixmap)


STYLE = '''
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #203832; }
QWidget#window { background: transparent; }
QLabel { background: transparent; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: #71827b; font-size: 12px; }
QLabel#badge { color: #347b61; background: #e4f2e9; border-radius: 11px; padding: 5px 10px; font-size: 11px; }
QFrame#hero { background: #e9f2eb; border: 1px solid #dfebe2; border-radius: 20px; }
QLabel#quota { font-family: "Segoe UI"; font-size: 66px; font-weight: 600; color: #183e30; }
QLabel#percent { font-family: "Segoe UI"; font-size: 26px; color: #547766; padding-bottom: 12px; }
QLabel#reset { font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 18px; font-weight: 600; color: #244939; }
QLabel#section { font-size: 13px; font-weight: 600; }
QFrame#settings, QFrame#pairing { background: #ffffff; border: 1px solid #e6ebe7; border-radius: 16px; }
QFrame#divider { background: #eaf0eb; max-height: 1px; border: none; }
QProgressBar { background: #d4e5d8; border: none; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #3e9471; border-radius: 3px; }
QComboBox, QSpinBox, QLineEdit { background: #f5f7f5; border: 1px solid #e2e8e3; border-radius: 9px; min-height: 34px; padding: 0 11px; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border: 1px solid #6b9b83; }
QLineEdit:read-only { border-color: transparent; background: #eef4ef; }
QLineEdit#pairCode { font-family: "Consolas"; font-size: 18px; font-weight: 600; min-height: 44px; border-radius: 11px; }
QPushButton#unpair { color: #bd454f; background: transparent; }
QPushButton#unpair:hover { background: #fbecef; }
QPushButton#unpair:disabled { color: #9ba8a0; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e9f2eb; selection-color: #203832; padding: 5px; }
QSpinBox { min-width: 80px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; height: 17px; border: none; background: transparent; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; height: 17px; border: none; background: transparent; }
QPushButton { background: #edf2ee; border: none; border-radius: 8px; padding: 8px 14px; font-weight: 500; }
QPushButton:hover { background: #e2ebe4; }
QPushButton:pressed { background: #d5e3da; }
QPushButton:disabled { color: #9ba8a0; }
QPushButton#windowControl { background: transparent; font-family: "Segoe UI"; font-size: 20px; padding: 0; border-radius: 7px; }
QPushButton#windowControl:hover { background: #e2ebe4; }
QPushButton#settingsControl { background: transparent; font-family: "Segoe MDL2 Assets"; font-size: 18px; padding: 0; border-radius: 7px; }
QPushButton#settingsControl:hover { background: #e2ebe4; }
QPushButton#primary { background: #255b44; color: #ffffff; border-radius: 11px; padding: 11px 16px; }
QPushButton#primary:hover { background: #1e4c38; }
QPushButton#primary:disabled { background: #82a08b; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #baccc0; border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:checked { background: #347b59; border-color: #347b59; image: url("@CHECK_ICON@"); }
QMenu { background: white; border: 1px solid #dfe6e0; padding: 5px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: #e9f2eb; }
QSlider::groove:horizontal { height: 4px; background: #d4e5d8; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #347b59; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #347b59; border-radius: 7px; }
'''.replace('@CHECK_ICON@',(ASSETS/'check.svg').as_posix())


def label(text, name=None):
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    return result


class Window(QWidget):
    def __init__(self, icon):
        super().__init__()
        self.setObjectName('window')
        self.setWindowTitle('Codex Desk')
        self.setWindowIcon(icon)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(430)
        self.settings = QSettings('CodexDesk', 'Desktop')
        self.startup = QSettings(r'HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run', QSettings.Format.NativeFormat)
        self.address = self.settings.value('device/address', '')
        self.device_name = self.settings.value('device/name', 'CodexDesk')
        self.device_id = self.settings.value('device/id', '')
        self.username = self.settings.value('screen/username',account_name())
        self.name_mode = int(self.settings.value('screen/name_mode',0))
        self.current_account = read_account()
        if self.name_mode==0:self.username=account_name()
        self.screen_theme = int(self.settings.value('screen/theme',2))
        self.brightness = int(self.settings.value('screen/brightness',100))
        self.screen_accent = int(self.settings.value('screen/accent',0))
        self.screen_layout = int(self.settings.value('screen/layout',1))
        self.next_sync = 0
        self.reset_at = 0
        self.last_success = False
        self.quitting = False
        self.upgrading = False
        self.last_contact = 0
        self.task_counts = {'running':0,'waiting':0,'unread':0}
        self.status_kind = 'muted'
        self.device_version = None
        self.release = None
        self.dark = self.effective_theme()==1
        self.build_ui()
        self.events = Events()
        self.bridge = DesktopBridge(self.events, self.address, self.screen_profile())
        self.events.ready.connect(self.ready)
        self.events.connection.connect(self.connection_changed)
        self.events.busy.connect(self.set_busy)
        self.events.updated.connect(self.update_quota)
        self.events.error.connect(self.show_error)
        self.events.scheduled.connect(self.schedule)
        self.events.firmware.connect(self.firmware_changed)
        self.events.upgrade_progress.connect(self.upgrade_progress)
        self.events.upgrade_done.connect(self.upgrade_done)
        self.events.profile_applied.connect(lambda:self.set_status('屏幕样式已发送','success'))
        self.events.tasks.connect(self.update_tasks)
        self.events.account.connect(self.account_changed)
        self.events.paired.connect(self.paired)
        self.events.contact.connect(self.contacted)
        self.events.stopped.connect(self.finish_quit)
        self.pair_button.clicked.connect(self.pair_clicked)
        self.unpair_button.clicked.connect(self.forget_device)
        self.pair_input.returnPressed.connect(self.pair_clicked)
        self.brightness_slider.valueChanged.connect(self.change_brightness)
        self.startup_check.toggled.connect(self.change_startup)
        self.sync_button.clicked.connect(self.manual_sync)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('Codex Desk · 蓝牙用量屏幕')
        menu = QMenu()
        menu.addAction('打开 Codex Desk', self.restore)
        menu.addAction('手动同步', self.manual_sync)
        self.release_action=menu.addAction('查看更新',self.open_release)
        self.release_action.setEnabled(False)
        menu.addSeparator()
        self.quit_action=menu.addAction('退出应用', self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.messageClicked.connect(self.open_release)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        QApplication.styleHints().colorSchemeChanged.connect(self.apply_theme)
        self.apply_theme()
        self.bridge.start()
        self.update_check=ReleaseCheck(self)
        self.update_check.checking.connect(self.checking_updates)
        self.update_check.found.connect(self.updates_found)
        self.update_check.failed.connect(self.update_check_failed)
        self.check_button.clicked.connect(self.update_check.check)
        self.update_check.start()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#34463e' if self.dark else '#dce7df'),1))
        painter.setBrush(QColor('#141e1a' if self.dark else '#f6f8f7'))
        painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),20,20)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and event.position().y()<80:
            self.windowHandle().startSystemMove()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        heading.addWidget(label('Codex Desk', 'title'))
        heading.addStretch()
        self.badge = label('准备连接', 'badge')
        heading.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        self.settings_button=QPushButton('\ue713')
        self.settings_button.setObjectName('settingsControl')
        self.settings_button.setFixedSize(27,28)
        self.settings_button.setToolTip('设置')
        self.settings_button.clicked.connect(self.open_settings)
        heading.addWidget(self.settings_button,alignment=Qt.AlignmentFlag.AlignTop)
        for symbol,action,tip in [('−',self.hide,'收起到托盘'),('×',self.hide,'收起到托盘')]:
            button=QPushButton(symbol)
            button.setObjectName('windowControl')
            button.setFixedSize(27,28)
            button.setToolTip(tip)
            button.clicked.connect(action)
            heading.addWidget(button,alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(heading)

        hero = QFrame()
        hero.setObjectName('hero')
        card = QVBoxLayout(hero)
        card.setContentsMargins(21, 17, 21, 17)
        card.setSpacing(8)
        account_row=QHBoxLayout()
        self.account_label=label(account_name(),'section')
        account_row.addWidget(self.account_label);account_row.addStretch()
        self.period = label('剩余额度', 'muted')
        account_row.addWidget(self.period);card.addLayout(account_row)
        value_row = QHBoxLayout()
        value_row.setSpacing(5)
        self.quota = label('—', 'quota')
        value_row.addWidget(self.quota)
        value_row.addWidget(label('%', 'percent'), alignment=Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch()
        self.until_reset = label('', 'muted')
        self.until_reset.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_row.addWidget(self.until_reset)
        card.addLayout(value_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        card.addWidget(self.progress)
        card.addSpacing(5)
        reset_row = QHBoxLayout()
        reset_text = QVBoxLayout()
        reset_text.setSpacing(3)
        reset_text.addWidget(label('下次重置 · 北京时间', 'muted'))
        self.reset_label = label('—', 'reset')
        reset_text.addWidget(self.reset_label)
        reset_row.addLayout(reset_text)
        reset_row.addStretch()
        self.resets_label = label('', 'muted')
        reset_row.addWidget(self.resets_label, alignment=Qt.AlignmentFlag.AlignBottom)
        card.addLayout(reset_row)
        layout.addWidget(hero)

        self.task_summary=label('','subtitle')
        self.task_summary.setTextFormat(Qt.TextFormat.RichText)
        self.task_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.task_summary)

        self.pair_card=QFrame()
        self.pair_card.setObjectName('pairing')
        pairing=QVBoxLayout(self.pair_card)
        pairing.setContentsMargins(17,15,17,15);pairing.setSpacing(10)
        pairing.addWidget(label('连接屏幕','section'))
        device_row=QHBoxLayout()
        self.pair_input=QLineEdit()
        self.pair_input.setObjectName('pairCode')
        self.pair_input.setInputMask('>HHHHHH-999999;·')
        self.pair_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pair_input.setAccessibleName('屏幕配对码')
        code_font=self.pair_input.font();code_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,1.5)
        self.pair_input.setFont(code_font)
        self.pair_button=QPushButton('连接')
        self.pair_button.setFixedHeight(44)
        self.pair_button.setEnabled(False)
        device_row.addWidget(self.pair_input,1);device_row.addWidget(self.pair_button)
        pairing.addLayout(device_row)
        pairing.addWidget(label('输入屏幕二维码下方的配对码','muted'))
        layout.addWidget(self.pair_card)

        self.sync_button = QPushButton('手动同步')
        self.sync_button.setObjectName('primary')
        self.sync_button.setEnabled(False)
        layout.addWidget(self.sync_button)
        self.status = label('', 'muted')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.preferences=QDialog(self,Qt.WindowType.Dialog|Qt.WindowType.FramelessWindowHint)
        self.preferences.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.preferences.setFixedWidth(390)
        outer=QVBoxLayout(self.preferences);outer.setContentsMargins(0,0,0,0)
        settings = QFrame()
        settings.setObjectName('settings')
        outer.addWidget(settings)
        controls = QVBoxLayout(settings)
        controls.setContentsMargins(22,20,22,20)
        controls.setSpacing(16)
        heading=QHBoxLayout();heading.addWidget(label('设置','title'));heading.addStretch()
        close=QPushButton('×');close.setObjectName('windowControl');close.setFixedSize(28,28)
        close.clicked.connect(self.preferences.reject);heading.addWidget(close);controls.addLayout(heading)
        device=QHBoxLayout()
        self.bound_device=label('','section');device.addWidget(self.bound_device);device.addStretch()
        self.unpair_button=QPushButton('解除配对');self.unpair_button.setObjectName('unpair')
        device.addWidget(self.unpair_button);controls.addLayout(device)
        self.device_address = label('已保存配对' if self.address else '配对码显示在屏幕二维码下方', 'muted')
        controls.addWidget(self.device_address)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        controls.addWidget(divider)
        speed_row = QHBoxLayout()
        speed_row.addWidget(label('画面亮度', 'section'))
        speed_row.addStretch()
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(5,100)
        self.brightness_slider.setValue(self.brightness)
        self.brightness_slider.setFixedWidth(144)
        self.brightness_slider.setEnabled(False)
        self.brightness_label = label(f'{self.brightness}%', 'muted')
        self.brightness_label.setFixedWidth(36)
        speed_row.addWidget(self.brightness_slider)
        speed_row.addWidget(self.brightness_label)
        controls.addLayout(speed_row)
        self.startup_check = QCheckBox('登录 Windows 时启动')
        self.startup_check.setChecked(self.startup.contains('CodexDesk'))
        preferences_row=QHBoxLayout()
        preferences_row.addWidget(self.startup_check)
        preferences_row.addStretch()
        self.style_button=QPushButton('屏幕样式')
        self.style_button.setEnabled(False)
        self.style_button.clicked.connect(self.edit_screen_style)
        preferences_row.addWidget(self.style_button)
        controls.addLayout(preferences_row)
        firmware_row=QHBoxLayout()
        firmware_row.addWidget(label('屏幕固件','section'))
        self.firmware_label=label('连接后读取','muted')
        firmware_row.addWidget(self.firmware_label)
        firmware_row.addStretch()
        self.upgrade_button=QPushButton('升级')
        self.upgrade_button.setEnabled(False)
        firmware_menu=QMenu(self)
        self.builtin_upgrade=firmware_menu.addAction('升级到内置版本 v'+FIRMWARE_VERSION,self.upgrade_builtin)
        firmware_menu.addAction('选择固件文件…',self.choose_firmware)
        self.upgrade_button.setMenu(firmware_menu)
        firmware_row.addWidget(self.upgrade_button)
        controls.addLayout(firmware_row)
        divider=QFrame();divider.setObjectName('divider');divider.setFixedHeight(1);controls.addWidget(divider)
        updates_row=QHBoxLayout()
        updates_row.addWidget(label('应用 v'+APP_VERSION,'section'));updates_row.addStretch()
        self.check_button=QPushButton('检查更新');updates_row.addWidget(self.check_button)
        controls.addLayout(updates_row)
        self.update_info=label('启动后自动检查 GitHub 更新','muted')
        self.update_info.setWordWrap(True);controls.addWidget(self.update_info)
        self.release_button=QPushButton('前往 GitHub 下载')
        self.release_button.clicked.connect(self.open_release)
        self.release_button.hide();controls.addWidget(self.release_button)
        self.refresh_pairing_ui()

    def open_settings(self):
        self.preferences.adjustSize()
        self.preferences.move(self.geometry().center()-self.preferences.rect().center())
        self.preferences.exec()

    def refresh_pairing_ui(self):
        self.pair_card.setVisible(not bool(self.address))
        self.bound_device.setText('CodexDesk · '+self.device_id if self.address else '未配对屏幕')
        self.unpair_button.setEnabled(bool(self.address) and not self.upgrading)
        self.setFixedHeight(500 if self.address else 640)

    def ready(self):
        self.pair_button.setEnabled(True)
        self.brightness_slider.setEnabled(True)
        self.style_button.setEnabled(True)

    def screen_profile(self):
        image=QImage(168,24,QImage.Format.Format_Mono)
        image.setColor(0,0xff000000);image.setColor(1,0xffffffff);image.fill(0)
        font=QFont('Microsoft YaHei UI');font.setPixelSize(20)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        painter=QPainter(image);painter.setFont(font);painter.setPen(Qt.GlobalColor.white)
        name=QFontMetrics(font).elidedText(self.username,Qt.TextElideMode.ElideRight,168)
        painter.drawText(image.rect(),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,name)
        painter.end()
        data=bytes(image.constBits());stride=image.bytesPerLine()
        bitmap=b''.join(data[y*stride:y*stride+21] for y in range(24))
        return self.effective_theme(),self.screen_accent,bitmap,self.screen_layout,self.brightness

    def effective_theme(self):
        if self.screen_theme == 2:
            return int(QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        return self.screen_theme

    def apply_theme(self, *_):
        self.dark = self.effective_theme()==1
        colors = {'#203832':'#e3ece6','#71827b':'#9aaa9f','#e4f2e9':'#253d31',
            '#347b61':'#8ed5b1','#e9f2eb':'#21382c','#dfebe2':'#354b3e','#183e30':'#d2f1df',
            '#547766':'#a6c1af','#244939':'#d2e8da','#ffffff':'#1b2821','#e6ebe7':'#34463a',
            '#eaf0eb':'#34463a','#d4e5d8':'#3b5143','#f5f7f5':'#24362b','#e2e8e3':'#405648',
            '#eef4ef':'#24362b','#edf2ee':'#2c4134','#e2ebe4':'#3b5143','#d5e3da':'#47614f',
            '#9ba8a0':'#65776b','#baccc0':'#557460','#dfe6e0':'#34463a',
            '#bd454f':'#ff969e','#fbecef':'#45272d'}
        style = STYLE
        if self.dark:
            style = re.sub(r'#[0-9a-f]{6}',lambda m:colors.get(m.group(),m.group()),style)
            style = style.replace('background: white','background: #1b2821')
            style += 'QPushButton#primary { color: #ffffff; }'
        QApplication.instance().setStyleSheet(style)
        self.refresh_state_colors()
        self.update()
        if hasattr(self.bridge,'loop'):
            self.bridge.set_profile(self.screen_profile())

    def edit_screen_style(self):
        dialog=QDialog(self.preferences,Qt.WindowType.Dialog|Qt.WindowType.FramelessWindowHint)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setFixedWidth(360)
        outer=QVBoxLayout(dialog);outer.setContentsMargins(0,0,0,0)
        panel=QFrame();panel.setObjectName('settings');outer.addWidget(panel)
        layout=QVBoxLayout(panel);layout.setContentsMargins(22,20,22,20);layout.setSpacing(12)
        heading=QHBoxLayout();heading.addWidget(label('屏幕样式','title'));heading.addStretch()
        close=QPushButton('×');close.setObjectName('windowControl');close.setFixedSize(28,28)
        close.clicked.connect(dialog.reject);heading.addWidget(close);layout.addLayout(heading)
        layout.addWidget(label('用户名','section'))
        name=QLineEdit(self.username);name.setObjectName('screenUsername');name.setMaxLength(32)
        layout.addWidget(name)
        follow=QCheckBox('跟随 Codex 登录账号');follow.setChecked(self.name_mode==0)
        name.setEnabled(self.name_mode!=0);follow.toggled.connect(lambda checked:name.setEnabled(not checked))
        layout.addWidget(follow)
        for title,items,current,key in [('界面',['基础样式','任务动态'],self.screen_layout,'screenLayout'),
                                         ('主题',['白天','黑夜','跟随系统'],self.screen_theme,'screenTheme'),
                                         ('强调色',['青绿','蓝色','暖橙'],self.screen_accent,'screenAccent')]:
            row=QHBoxLayout();row.addWidget(label(title,'section'));row.addStretch()
            combo=QComboBox();combo.setObjectName(key);combo.addItems(items);combo.setCurrentIndex(current)
            combo.setMinimumWidth(180);row.addWidget(combo);layout.addLayout(row)
        apply=QPushButton('应用到屏幕');apply.setObjectName('primary');apply.clicked.connect(dialog.accept)
        layout.addSpacing(4);layout.addWidget(apply)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.name_mode=0 if follow.isChecked() else 1
            self.username=account_name() if self.name_mode==0 else name.text()
            self.screen_theme=dialog.findChild(QComboBox,'screenTheme').currentIndex()
            self.screen_accent=dialog.findChild(QComboBox,'screenAccent').currentIndex()
            self.screen_layout=dialog.findChild(QComboBox,'screenLayout').currentIndex()
            for key,value in [('username',self.username),('name_mode',self.name_mode),('theme',self.screen_theme),('accent',self.screen_accent),('layout',self.screen_layout)]:
                self.settings.setValue('screen/'+key,value)
            self.apply_theme()

    def connection_changed(self, state, address):
        self.badge.setText(state)
        self.device_address.setText(('已连接 · '+self.device_id) if state=='已连接' and self.device_id else state if address else '配对码显示在屏幕二维码下方')
        self.pair_button.setEnabled(state!='配对中' and not self.upgrading)
        self.pair_input.setEnabled(state!='配对中' and not self.upgrading)
        self.unpair_button.setEnabled(bool(self.address) and not self.upgrading)
        self.sync_button.setEnabled(state == '已连接' and bool(self.current_account))
        self.upgrade_button.setEnabled(state in ('已连接','请升级固件') and not self.upgrading)
        if state=='已连接':
            self.last_contact=time.time()
        self.refresh_state_colors()

    def update_tasks(self, data):
        self.task_counts={key:data[key] for key in ('running','waiting','unread')}
        self.refresh_state_colors()

    def refresh_state_colors(self):
        colors = {'success':'#81d6ae','waiting':'#ffc278','unread':'#91bdff','error':'#ff969e','muted':'#9aaa9f'} if self.dark else {
            'success':'#27815c','waiting':'#b4730b','unread':'#3475c6','error':'#c04450','muted':'#71827b'}
        self.task_summary.setText('&nbsp;&nbsp; · &nbsp;&nbsp;'.join(
            f'<span style="color:{colors[state]}">{title} {self.task_counts[key]}</span>'
            for key,title,state in [('running','进行中','success'),('waiting','待回答','waiting'),('unread','未读','unread')]))
        state={'已连接':'success','正在连接':'unread','配对中':'unread','请升级固件':'waiting','升级中':'waiting'}.get(self.badge.text(),'muted')
        color=colors[state]
        self.badge.setStyleSheet(f'color:{color};background:rgba({QColor(color).red()},{QColor(color).green()},{QColor(color).blue()},24);')
        self.status.setStyleSheet(f'color:{colors[self.status_kind]};')

    def set_status(self, text, kind='muted'):
        self.status_kind=kind
        self.status.setText(text)
        self.refresh_state_colors()

    def account_changed(self, account):
        previous=self.current_account
        self.current_account=account
        self.account_label.setText(account['name'] if account else '未登录 Codex')
        if previous!=account:
            self.quota.setText('—');self.progress.setValue(0);self.reset_label.setText('—')
            self.period.setText('剩余额度')
            self.resets_label.setText('');self.until_reset.setText('');self.reset_at=0
        if self.name_mode==0:
            self.username=account['name'] if account else '未登录'
            self.bridge.set_profile(self.screen_profile())
        self.sync_button.setEnabled(bool(account) and self.badge.text()=='已连接')

    def manual_sync(self):
        if self.sync_button.isEnabled():
            self.set_busy(True)
            self.bridge.refresh()

    def pair_clicked(self):
        code=re.sub(r'[\s-]','',self.pair_input.text()).upper()
        if not re.fullmatch(r'[0-9A-F]{6}[0-9]{6}',code):
            self.set_status('请输入完整的屏幕配对码','waiting')
            return
        self.pair_button.setEnabled(False)
        self.pair_input.setEnabled(False)
        self.bridge.connect_code(code)

    def forget_device(self):
        self.unpair_button.setEnabled(False)
        self.bridge.forget()

    def paired(self,address,identifier):
        self.address=address;self.device_id=identifier
        self.settings.setValue('device/address',address);self.settings.setValue('device/id',identifier)
        self.pair_input.clear()
        self.pair_button.setEnabled(True)
        self.pair_input.setEnabled(True)
        self.refresh_pairing_ui()
        if not address:
            self.preferences.accept()
            self.pair_input.setFocus()
        self.set_status('配对已保存' if address else '已解除配对','success')

    def set_busy(self, busy):
        self.sync_button.setEnabled(not busy and not self.upgrading and bool(self.current_account) and self.badge.text()=='已连接')
        self.sync_button.setText('手动同步中…' if busy else '手动同步')

    def update_quota(self, data):
        self.last_success = True
        self.quota.setText(str(data['remaining']))
        self.progress.setValue(data['remaining'])
        remaining=data['remaining']
        color='#23a973' if remaining>70 else '#d3a416' if remaining>=50 else '#e87c2d' if remaining>=20 else '#de4c55'
        self.progress.setStyleSheet(f'QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}')
        period = '周额度' if data['window_minutes'] >= 10080 else '当前周期'
        self.period.setText(f"{data['plan'].capitalize()} · {period}剩余")
        self.reset_at = data['reset']
        reset = datetime.fromtimestamp(self.reset_at, timezone(timedelta(hours=8)))
        self.reset_label.setText(reset.strftime('%m月%d日  %H:%M'))
        self.resets_label.setText('' if data['resets'] is None else f"剩余 {data['resets']} 次重置")
        self.status.setToolTip('')
        self.set_status('上次更新 '+datetime.fromtimestamp(data['synced_at']).strftime('%H:%M:%S'))
        self.tray.setToolTip(f"Codex Desk · 剩余 {data['remaining']}%\n{reset:%m月%d日 %H:%M} 重置")
        self.tick()

    def schedule(self, when):
        self.next_sync = when
        self.tick()

    def tick(self):
        if self.badge.text()=='已连接' and self.last_contact and time.time()-self.last_contact>=180:
            self.connection_changed('离线',self.address)
        if self.reset_at:
            left = max(0, int(self.reset_at - time.time()))
            days, hours = left // 86400, left // 3600 % 24
            self.until_reset.setText(f'{days} 天 {hours} 小时\n后重置' if days else f'{left//3600} 小时 {left//60%60} 分\n后重置')

    def upgrade_builtin(self):
        root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        self.start_upgrade(root/'build'/'codex_status.img')

    def firmware_changed(self,version):
        self.device_version=version
        self.firmware_label.setText('v'+version)
        newer=version_tuple(FIRMWARE_VERSION)>version_tuple(version)
        self.builtin_upgrade.setEnabled(newer)
        self.builtin_upgrade.setText('升级到内置版本 v'+FIRMWARE_VERSION if newer else '内置固件 v'+FIRMWARE_VERSION)
        if self.release:
            self.show_available_updates()

    def checking_updates(self):
        self.check_button.setEnabled(False)
        self.update_info.setText('正在检查 GitHub…')
        self.update_info.setToolTip('')

    def updates_found(self, release):
        self.release=release
        self.check_button.setEnabled(True)
        self.show_available_updates()

    def show_available_updates(self):
        latest=self.release
        app_new=version_tuple(latest['app']['version'])>version_tuple(APP_VERSION)
        firmware_new=bool(self.device_version and version_tuple(latest['firmware']['version'])>version_tuple(self.device_version))
        lines=['APP v'+(latest['app']['version'] if app_new else APP_VERSION)+(' 可用' if app_new else ' · 已是最新')]
        lines.append('固件 v'+(latest['firmware']['version'] if firmware_new or not self.device_version else self.device_version)+(' 可用' if firmware_new else ' · 已是最新' if self.device_version else ' · 连接后比较'))
        self.update_info.setText('\n'.join(lines))
        available=app_new or firmware_new
        self.release_button.setVisible(available)
        self.release_action.setEnabled(available)
        self.settings_button.setToolTip('设置 · 有可用更新' if available else '设置')
        notice='|'.join([latest['tag'],str(app_new),str(firmware_new)])
        if available and self.settings.value('updates/notified','')!=notice:
            self.tray.showMessage('Codex Desk 有可用更新','\n'.join(lines)+'\n点击查看下载，安装由你手动进行。')
            self.settings.setValue('updates/notified',notice)
        self.preferences.adjustSize()

    def update_check_failed(self, detail):
        self.check_button.setEnabled(True)
        self.update_info.setText('暂时无法检查更新，点击重试')
        self.update_info.setToolTip(detail)

    def open_release(self):
        QDesktopServices.openUrl(QUrl(self.release['url']))

    def choose_firmware(self):
        path,_=QFileDialog.getOpenFileName(self,'选择屏幕固件','','屏幕固件 (*.img)')
        if path:
            self.start_upgrade(Path(path))

    def start_upgrade(self,path):
        self.upgrading=True
        self.next_sync=0
        for control in (self.pair_input,self.pair_button,self.unpair_button,self.brightness_slider,self.upgrade_button,self.sync_button,self.style_button):
            control.setEnabled(False)
        self.preferences.accept()
        self.set_status('准备升级屏幕…','waiting')
        self.bridge.upgrade(path)

    def upgrade_progress(self,percent,stage):
        self.badge.setText('升级中')
        self.sync_button.setText(f'{stage} · {percent}%')
        self.set_status('升级后自动恢复额度同步','waiting')

    def upgrade_done(self,success,detail):
        self.upgrading=False
        for control in (self.pair_input,self.pair_button,self.brightness_slider,self.upgrade_button,self.sync_button,self.style_button):
            control.setEnabled(True)
        self.sync_button.setText('手动同步')
        self.unpair_button.setEnabled(bool(self.address))
        self.set_status('升级完成 · v'+detail if success else '升级未完成','success' if success else 'error')
        self.status.setToolTip('' if success else detail)

    def contacted(self, when):
        self.last_contact=when
        if self.badge.text()=='离线':
            self.connection_changed('已连接',self.address)

    def change_brightness(self, value):
        self.brightness=value
        self.brightness_label.setText(f'{value}%')
        self.settings.setValue('screen/brightness',value)
        self.bridge.set_profile(self.screen_profile())

    def change_startup(self, enabled):
        if enabled:
            command = [sys.executable, '--background'] if getattr(sys, 'frozen', False) else [
                str(Path(sys.executable).with_name('pythonw.exe')), str(Path(__file__).resolve()), '--background']
            self.startup.setValue('CodexDesk', subprocess.list2cmdline(command))
        else:
            self.startup.remove('CodexDesk')
        self.startup.sync()

    def show_error(self, message, detail):
        self.last_success = False
        self.pair_button.setEnabled(True)
        self.unpair_button.setEnabled(bool(self.address) and not self.upgrading)
        self.set_status(message,'error')
        self.status.setToolTip(detail)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.restore()

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.quit_action.setEnabled(False)
        self.timer.stop()
        self.update_check.stop()
        self.preferences.reject()
        self.hide()
        self.bridge.stop()

    def finish_quit(self):
        self.tray.hide()
        QApplication.instance().quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    server_name = 'CodexDesk-' + os.environ['USERNAME']
    existing = QLocalSocket()
    existing.connectToServer(server_name)
    if existing.waitForConnected(200):
        existing.write(b'show')
        existing.waitForBytesWritten(200)
        return
    icon = app_icon()
    app.setWindowIcon(icon)
    window = Window(icon)
    server = QLocalServer()
    server.listen(server_name)
    def activate():
        connection = server.nextPendingConnection()
        connection.disconnectFromServer()
        window.restore()
    server.newConnection.connect(activate)
    if '--background' not in sys.argv:
        window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
