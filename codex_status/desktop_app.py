import os
from pathlib import Path
import subprocess
import sys
import time
import re
from datetime import datetime, timezone, timedelta

from PySide6.QtCore import QObject, Signal, QSettings, QTimer, Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QAction, QImage, QFontMetrics
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QProgressBar,
    QSystemTrayIcon, QMenu, QFileDialog, QDialog, QLineEdit,
)
from desktop_bridge import DesktopBridge
from account import read_account


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
QFrame#settings { background: #ffffff; border: 1px solid #e6ebe7; border-radius: 16px; }
QFrame#divider { background: #eaf0eb; max-height: 1px; border: none; }
QProgressBar { background: #d4e5d8; border: none; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #3e9471; border-radius: 3px; }
QComboBox, QSpinBox, QLineEdit { background: #f5f7f5; border: 1px solid #e2e8e3; border-radius: 9px; min-height: 34px; padding: 0 11px; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border: 1px solid #6b9b83; }
QLineEdit:read-only { border-color: transparent; background: #eef4ef; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e9f2eb; selection-color: #203832; padding: 5px; }
QSpinBox { min-width: 80px; }
QPushButton { background: #edf2ee; border: none; border-radius: 8px; padding: 8px 14px; font-weight: 500; }
QPushButton:hover { background: #e2ebe4; }
QPushButton:pressed { background: #d5e3da; }
QPushButton:disabled { color: #9ba8a0; }
QPushButton#windowControl { background: transparent; font-family: "Segoe UI"; font-size: 20px; padding: 0; border-radius: 7px; }
QPushButton#windowControl:hover { background: #e2ebe4; }
QPushButton#primary { background: #255b44; color: #ffffff; border-radius: 11px; padding: 11px 16px; }
QPushButton#primary:hover { background: #1e4c38; }
QPushButton#primary:disabled { background: #82a08b; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #baccc0; border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:checked { background: #347b59; border-color: #347b59; }
QMenu { background: white; border: 1px solid #dfe6e0; padding: 5px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: #e9f2eb; }
'''


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
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(430, 710)
        self.settings = QSettings('CodexDesk', 'Desktop')
        self.startup = QSettings(r'HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run', QSettings.Format.NativeFormat)
        self.address = self.settings.value('device/address', '')
        self.device_name = self.settings.value('device/name', 'CodexDesk')
        self.device_id = self.settings.value('device/id', '')
        self.interval = int(self.settings.value('sync/interval', 60))
        self.username = self.settings.value('screen/username',account_name())
        self.name_mode = int(self.settings.value('screen/name_mode',0))
        self.current_account = read_account()
        if self.name_mode==0:self.username=account_name()
        self.screen_theme = int(self.settings.value('screen/theme',0))
        self.screen_accent = int(self.settings.value('screen/accent',0))
        self.screen_layout = int(self.settings.value('screen/layout',1))
        self.next_sync = 0
        self.reset_at = 0
        self.last_success = False
        self.quitting = False
        self.upgrading = False
        self.build_ui()
        self.events = Events()
        self.bridge = DesktopBridge(self.events, self.address, self.interval, self.screen_profile())
        self.events.ready.connect(self.ready)
        self.events.connection.connect(self.connection_changed)
        self.events.busy.connect(self.set_busy)
        self.events.updated.connect(self.update_quota)
        self.events.error.connect(self.show_error)
        self.events.scheduled.connect(self.schedule)
        self.events.firmware.connect(self.firmware_changed)
        self.events.upgrade_progress.connect(self.upgrade_progress)
        self.events.upgrade_done.connect(self.upgrade_done)
        self.events.profile_applied.connect(lambda:self.status.setText('屏幕样式已发送'))
        self.events.tasks.connect(lambda data:self.task_summary.setText(f'进行中 {data["running"]}  ·  待回答 {data["waiting"]}  ·  未读 {data["unread"]}'))
        self.events.account.connect(self.account_changed)
        self.events.paired.connect(self.paired)
        self.pair_button.clicked.connect(self.pair_clicked)
        self.pair_input.returnPressed.connect(self.pair_clicked)
        self.interval_spin.valueChanged.connect(self.change_interval)
        self.startup_check.toggled.connect(self.change_startup)
        self.sync_button.clicked.connect(self.manual_sync)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('Codex Desk · 蓝牙用量屏幕')
        menu = QMenu()
        menu.addAction('打开 Codex Desk', self.restore)
        menu.addAction('手动同步', self.manual_sync)
        menu.addSeparator()
        menu.addAction('退出', self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.bridge.start()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#dce7df'),1))
        painter.setBrush(QColor('#f6f8f7'))
        painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),20,20)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and event.position().y()<80:
            self.windowHandle().startSystemMove()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(label('Codex Desk', 'title'))
        self.task_summary=label('用量与任务动态', 'subtitle')
        titles.addWidget(self.task_summary)
        heading.addLayout(titles)
        heading.addStretch()
        self.badge = label('准备连接', 'badge')
        heading.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        for symbol,action,tip in [('−',self.showMinimized,'最小化'),('×',self.close,'收起到托盘')]:
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

        settings = QFrame()
        settings.setObjectName('settings')
        controls = QVBoxLayout(settings)
        controls.setContentsMargins(17, 15, 17, 15)
        controls.setSpacing(10)
        controls.addWidget(label('蓝牙屏幕', 'section'))
        device_row = QHBoxLayout()
        self.pair_input=QLineEdit()
        self.pair_input.setPlaceholderText('输入屏幕配对码')
        self.pair_input.setMaxLength(15)
        self.pair_input.setReadOnly(bool(self.address))
        self.pair_input.setText('CodexDesk'+(' · '+self.device_id if self.device_id else '') if self.address else '')
        self.pair_button=QPushButton('解除' if self.address else '连接')
        self.pair_button.setEnabled(False)
        device_row.addWidget(self.pair_input,1)
        device_row.addWidget(self.pair_button)
        controls.addLayout(device_row)
        self.device_address = label('已保存配对' if self.address else '配对码显示在屏幕二维码下方', 'muted')
        controls.addWidget(self.device_address)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        controls.addWidget(divider)
        speed_row = QHBoxLayout()
        speed_row.addWidget(label('后台更新间隔', 'section'))
        speed_row.addStretch()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 86400)
        self.interval_spin.setSuffix(' 秒')
        self.interval_spin.setValue(self.interval)
        self.interval_spin.setKeyboardTracking(False)
        self.interval_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.interval_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.interval_spin.lineEdit().setStyleSheet('border:none; background:transparent; padding:0; min-height:0;')
        self.interval_spin.setEnabled(False)
        speed_row.addWidget(self.interval_spin)
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
        self.builtin_upgrade=firmware_menu.addAction('升级到内置版本 v1.5.0',self.upgrade_builtin)
        firmware_menu.addAction('选择固件文件…',self.choose_firmware)
        self.upgrade_button.setMenu(firmware_menu)
        firmware_row.addWidget(self.upgrade_button)
        controls.addLayout(firmware_row)
        layout.addWidget(settings)

        self.sync_button = QPushButton('手动同步')
        self.sync_button.setObjectName('primary')
        self.sync_button.setEnabled(False)
        layout.addWidget(self.sync_button)
        self.status = label('', 'muted')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

    def ready(self):
        self.pair_button.setEnabled(True)
        self.interval_spin.setEnabled(True)
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
        return self.screen_theme,self.screen_accent,bitmap,self.screen_layout

    def edit_screen_style(self):
        dialog=QDialog(self,Qt.WindowType.Dialog|Qt.WindowType.FramelessWindowHint)
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
                                         ('主题',['浅色','深色'],self.screen_theme,'screenTheme'),
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
            self.bridge.set_profile(self.screen_profile())

    def connection_changed(self, state, address):
        self.badge.setText(state)
        self.device_address.setText(('已连接 · '+self.device_id) if state=='已连接' and self.device_id else state if address else '配对码显示在屏幕二维码下方')
        self.pair_button.setEnabled(state!='配对中' and not self.upgrading)
        self.sync_button.setEnabled(state == '已连接' and bool(self.current_account))
        self.upgrade_button.setEnabled(state=='已连接' and not self.upgrading)

    def account_changed(self, account):
        previous=self.current_account
        self.current_account=account
        self.account_label.setText(account['name'] if account else '未登录 Codex')
        if previous!=account:
            self.quota.setText('—');self.progress.setValue(0);self.reset_label.setText('—')
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
        if self.address:
            self.pair_button.setEnabled(False)
            self.bridge.forget()
            return
        code=re.sub(r'[\s-]','',self.pair_input.text()).upper()
        if not re.fullmatch(r'[0-9A-F]{6}[0-9]{6}',code):
            self.status.setText('请输入完整配对码，例如 A1B2C3-123456')
            return
        self.pair_button.setEnabled(False)
        self.bridge.connect_code(code)

    def paired(self,address,identifier):
        self.address=address;self.device_id=identifier
        self.settings.setValue('device/address',address);self.settings.setValue('device/id',identifier)
        self.pair_input.setReadOnly(bool(address))
        self.pair_input.setText('CodexDesk · '+identifier if address else '')
        self.pair_button.setText('解除' if address else '连接')
        self.pair_button.setEnabled(True)
        self.status.setText('配对已保存' if address else '已解除配对')

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
        self.resets_label.setText('' if data['resets'] is None else f"免费重置 {data['resets']} 次")
        self.badge.setText('已连接')
        self.status.setToolTip('')
        self.status.setText('上次更新 '+datetime.fromtimestamp(data['synced_at']).strftime('%H:%M:%S'))
        self.tray.setToolTip(f"Codex Desk · 剩余 {data['remaining']}%\n{reset:%m月%d日 %H:%M} 重置")
        self.tick()

    def schedule(self, when):
        self.next_sync = when
        self.tick()

    def tick(self):
        if self.reset_at:
            left = max(0, int(self.reset_at - time.time()))
            days, hours = left // 86400, left // 3600 % 24
            self.until_reset.setText(f'{days} 天 {hours} 小时\n后重置' if days else f'{left//3600} 小时 {left//60%60} 分\n后重置')

    def upgrade_builtin(self):
        root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
        self.start_upgrade(root/'build'/'codex_status.img')

    def firmware_changed(self,version):
        self.firmware_label.setText('v'+version)
        self.builtin_upgrade.setEnabled(version!='1.5.0')
        self.builtin_upgrade.setText('已是内置最新版 v1.5.0' if version=='1.5.0' else '升级到内置版本 v1.5.0')

    def choose_firmware(self):
        path,_=QFileDialog.getOpenFileName(self,'选择屏幕固件','','屏幕固件 (*.img)')
        if path:
            self.start_upgrade(Path(path))

    def start_upgrade(self,path):
        self.upgrading=True
        self.next_sync=0
        for control in (self.pair_input,self.pair_button,self.interval_spin,self.upgrade_button,self.sync_button,self.style_button):
            control.setEnabled(False)
        self.status.setText('准备升级屏幕…')
        self.bridge.upgrade(path)

    def upgrade_progress(self,percent,stage):
        self.badge.setText('升级中')
        self.sync_button.setText(f'{stage} · {percent}%')
        self.status.setText('升级后自动恢复额度同步')

    def upgrade_done(self,success,detail):
        self.upgrading=False
        for control in (self.pair_input,self.pair_button,self.interval_spin,self.upgrade_button,self.sync_button,self.style_button):
            control.setEnabled(True)
        self.sync_button.setText('手动同步')
        self.status.setText('升级完成 · v'+detail if success else '升级未完成')
        self.status.setToolTip('' if success else detail)

    def change_interval(self, seconds):
        self.settings.setValue('sync/interval', seconds)
        self.bridge.set_interval(seconds)

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
        self.status.setText(message)
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
        self.quitting = True
        self.bridge.stop()
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
