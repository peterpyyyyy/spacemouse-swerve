"""Standalone macOS launcher and embedded game; all device reads stay on this Mac."""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from runtime_paths import app_data_dir, resource_path

HELPER = "/Applications/3DconnexionHelper.app"
HELPER_PATTERN = r"^/Applications/3DconnexionHelper[.]app/Contents/MacOS/3DconnexionHelper($| )"


class DriverSession:
    """Keep 3DxWare running; stopping it can turn the cap into a system mouse."""
    def prepare(self):
        result = subprocess.run(["/usr/bin/pgrep", "-f", HELPER_PATTERN], capture_output=True, text=True)
        if not result.stdout.strip() and Path(HELPER).exists():
            subprocess.Popen(["/usr/bin/open", "-g", HELPER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def restore(self):
        self.prepare()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", action="store_true")
    parser.add_argument("--smoke-test", type=Path)
    parser.add_argument("--remote-debugging-port")
    args = parser.parse_args()
    data_dir = app_data_dir()
    os.environ["SPACEMOUSE_DATA_DIR"] = str(data_dir)
    logging.basicConfig(filename=data_dir / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.simulator:
        from swerve_sim import App
        App().run()
        return 0
    if args.remote_debugging_port:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = args.remote_debugging_port

    from PySide6.QtCore import QLockFile, QProcess, QTimer, Qt, QUrl
    from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPalette, QPainter
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
        QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
        QPushButton, QScrollArea, QSizePolicy, QToolBar, QVBoxLayout, QWidget)
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from spacemouse_hid import HIDSpaceMouse
    from spacemouse_driver import DriverSpaceMouse, FRAMEWORK
    from swerve_sim import Calibration, InputProcessor, MODES, SpaceMouseView
    from app_i18n import translate
    import pygame
    from spacemouse_bridge import PRESETS, anti_deadzone

    app = QApplication([sys.argv[0]])
    app.setApplicationName("SpaceMouse Swerve")
    app.setOrganizationName("SpaceMouse Swerve")
    app.setWindowIcon(QIcon(str(resource_path("assets/app-icon.svg"))))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#14161e"))
    palette.setColor(QPalette.WindowText, QColor("#e9ecf5"))
    palette.setColor(QPalette.Base, QColor("#1c202b"))
    palette.setColor(QPalette.Text, QColor("#e9ecf5"))
    palette.setColor(QPalette.Button, QColor("#282d3c"))
    palette.setColor(QPalette.ButtonText, QColor("#e9ecf5"))
    palette.setColor(QPalette.Highlight, QColor("#8265ef"))
    app.setPalette(palette)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget { font-family: 'PingFang SC'; font-size: 13px; }
        QPushButton { background:#292e3e; border:1px solid #3c4359; border-radius:7px; padding:9px 12px; }
        QPushButton:hover { background:#363d51; }
        QPushButton:checked { background:#7252d6; }
        QPushButton:disabled { color:#747b8d; }
        QComboBox, QDoubleSpinBox { background:#202535; border:1px solid #3c4359; border-radius:6px; padding:6px; }
        QProgressBar { border:0; border-radius:3px; background:#282e3d; text-align:center; height:16px; }
        QProgressBar::chunk { background:#7863d4; border-radius:3px; }
        QLabel#muted { color:#a1a9bd; }
    """)
    lock = QLockFile(str(data_dir / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "SpaceMouse Swerve", "App 已在运行，请在 Dock 中打开现有窗口。")
        return 0

    class GamePage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            logging.info("web: %s (%s:%s)", message, source, line)

        def acceptNavigationRequest(self, url, nav_type, is_main):
            if not is_main or url.scheme() in ("about", "data"):
                return True
            return url.scheme() == "https" and url.host() in ("tylerhandel.github.io", "www.frc4206.com", "frc4206.com")

    class PoseView(QWidget):
        def __init__(self,parent):
            super().__init__(parent)
            self.setFixedSize(218,190)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.view = SpaceMouseView((216,165))
            self.raw = [0.0]*6

        def paintEvent(self,event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(18,20,26,235))
            painter.setPen(QColor('#535875'))
            painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),10,10)
            frame = self.view.render(self.raw)
            pixels = pygame.image.tobytes(frame,'RGB')
            image = QImage(pixels,216,165,216*3,QImage.Format_RGB888)
            painter.drawImage(1,23,image)
            painter.setPen(QColor('#cfc6ef'))
            painter.drawText(12,18,'SpaceMouse · 3D')

    class GameView(QWebEngineView):
        def resizeEvent(self,event):
            super().resizeEvent(event)
            if hasattr(self,'pose'):
                self.pose.move(max(8,self.width()-self.pose.width()-14),14)
                self.pose.raise_()

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("SpaceMouse Swerve")
            self.resize(1440, 900)
            self.setMinimumSize(1024, 700)
            self.driver = DriverSession()
            self.device = None
            self.next_scan = 0.0
            self.proc = InputProcessor()
            self.loaded = False
            self.is_active = True
            self.child = None
            self.smoke_finished = False
            self.started = time.monotonic()
            self.settings_file = data_dir / "app_settings.json"
            try:
                prefs = json.loads(self.settings_file.read_text())
                if not isinstance(prefs, dict): prefs = {}
            except (OSError, ValueError):
                prefs = {}
            self.language_code = prefs.get('language','zh')
            self.device_status = '正在准备设备…'
            self.web_status = '正在加载游戏…'
            self.toolbar = QToolBar()
            self.toolbar.setMovable(False)
            self.addToolBar(self.toolbar)
            self.sidebar_action = QAction('参数栏',self)
            self.sidebar_action.setCheckable(True)
            self.sidebar_action.setChecked(bool(prefs.get('sidebar',True)))
            self.toolbar.addAction(self.sidebar_action)
            self.pose_action = QAction('3D 姿态',self)
            self.pose_action.setCheckable(True)
            self.pose_action.setChecked(bool(prefs.get('pose',True)))
            self.toolbar.addAction(self.pose_action)
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
            self.toolbar.addWidget(spacer)
            self.language = QComboBox()
            self.language.addItems(['简体中文','English'])
            self.language.setCurrentIndex(1 if self.language_code=='en' else 0)
            self.toolbar.addWidget(self.language)
            outer = QWidget()
            layout = QHBoxLayout(outer)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.setCentralWidget(outer)
            sidebar = QFrame()
            scroll = QScrollArea()
            scroll.setFixedWidth(270)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(sidebar)
            self.sidebar_scroll=scroll
            col = QVBoxLayout(sidebar)
            col.setContentsMargins(20, 24, 20, 20)
            col.setSpacing(12)
            title = QLabel("SPACEMOUSE\nSWERVE")
            title.setStyleSheet("font-size:25px;font-weight:700;letter-spacing:2px;color:#eee9ff")
            col.addWidget(title)
            subtitle = QLabel("连接 · 操控 · 开始比赛")
            subtitle.setObjectName("muted")
            col.addWidget(subtitle)
            self.device_label = QLabel("正在准备设备…")
            self.device_label.setWordWrap(True)
            self.device_label.setStyleSheet("color:#7ee6ad;padding-top:12px")
            col.addWidget(self.device_label)
            self.web_label = QLabel("正在加载游戏…")
            self.web_label.setWordWrap(True)
            self.web_label.setObjectName("muted")
            col.addWidget(self.web_label)
            self.games = QComboBox()
            self.games.addItems([p["name"] for p in PRESETS])
            saved = prefs.get("game", "rebuilt")
            self.games.setCurrentIndex(next((i for i,p in enumerate(PRESETS) if p["key"] == saved), 0))
            col.addWidget(self.games)
            self.reload_button = QPushButton("重新载入游戏")
            col.addWidget(self.reload_button)
            self.pause_button = QPushButton("暂停输入")
            self.pause_button.setCheckable(True)
            self.pause_button.toggled.connect(lambda paused:self.pause_button.setText(self.t("继续输入" if paused else "暂停输入")))
            col.addWidget(self.pause_button)
            self.reconnect_button = QPushButton("重新连接设备")
            self.reconnect_button.clicked.connect(self.reconnect)
            col.addWidget(self.reconnect_button)
            self.mode = QComboBox()
            self.mode.addItems(MODES)
            self.mode.setCurrentText(prefs.get("mode", "FUSE") if prefs.get("mode") in MODES else "FUSE")
            col.addWidget(QLabel("融合方式"))
            col.addWidget(self.mode)
            self.gain = QDoubleSpinBox()
            self.gain.setRange(.3, 3.0)
            self.gain.setSingleStep(.1)
            try: self.gain.setValue(float(prefs.get("gain",1.0)))
            except (TypeError,ValueError): self.gain.setValue(1.0)
            self.gain.setPrefix("灵敏度  ")
            col.addWidget(self.gain)
            self.invert = QCheckBox("反转旋转方向")
            col.addWidget(self.invert)
            self.bars = []
            for name in ("左右推", "前后推", "上下压", "前后倾", "左右倾", "扭转"):
                row = QHBoxLayout()
                label = QLabel(name)
                label.setFixedWidth(48)
                row.addWidget(label)
                bar = QProgressBar()
                bar.setRange(-100, 100)
                bar.setValue(0)
                bar.setFormat("0.00")
                row.addWidget(bar)
                col.addLayout(row)
                self.bars.append(bar)
            col.addStretch()
            self.practice_button = QPushButton("校准 / 本地练习")
            self.practice_button.clicked.connect(self.practice)
            col.addWidget(self.practice_button)
            import_button = QPushButton("导入已有校准")
            import_button.clicked.connect(self.import_calibration)
            col.addWidget(import_button)
            hint = QLabel("点击游戏画面后使用键盘\nJ 吸球  ·  K 射球\nL 传球  ·  ; 吐球\n\n使用官方驱动接入，退出后恢复 CAD 控制")
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            col.addWidget(hint)
            layout.addWidget(scroll)
            self.web = GameView()
            self.web.pose = PoseView(self.web)
            self.pose_action.toggled.connect(self.web.pose.setVisible)
            self.web.pose.setVisible(self.pose_action.isChecked())
            self.sidebar_action.toggled.connect(scroll.setVisible)
            scroll.setVisible(self.sidebar_action.isChecked())
            self.profile = QWebEngineProfile("SpaceMouseSwerve", self)
            self.profile.setPersistentStoragePath(str(data_dir / "Browser"))
            self.profile.setCachePath(str(data_dir / "Cache"))
            self.page = GamePage(self.profile, self.web)
            self.web.setPage(self.page)
            self.page.settings().setAttribute(QWebEngineSettings.WebGLEnabled, True)
            script = QWebEngineScript()
            script.setName("SpaceMouse native gamepad")
            script.setWorldId(QWebEngineScript.MainWorld)
            script.setInjectionPoint(QWebEngineScript.DocumentReady)
            script.setRunsOnSubFrames(False)
            source = resource_path("spacemouse_gamepad.js").read_text(encoding="utf-8")
            policy = resource_path('desktop_policy.js').read_text(encoding='utf-8')
            script.setSourceCode("if(['tylerhandel.github.io','www.frc4206.com','frc4206.com'].includes(location.hostname)){\n" + policy + source + "\n}")
            self.page.scripts().insert(script)
            layout.addWidget(self.web, 1)
            self.web.loadStarted.connect(self.load_started)
            self.web.loadFinished.connect(self.load_finished)
            self.games.currentIndexChanged.connect(self.load_game)
            self.reload_button.clicked.connect(self.load_game)
            self.translatable=[]
            for widget in sidebar.findChildren(QWidget):
                if isinstance(widget,(QLabel,QPushButton,QCheckBox)) and widget not in (self.device_label,self.web_label,self.pause_button):
                    self.translatable.append((widget,widget.text()))
            self.language.currentIndexChanged.connect(self.update_language)
            self.update_language()
            app.applicationStateChanged.connect(self.activation)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(16)
            self.monitor = QTimer(self)
            self.monitor.timeout.connect(self.monitor_page)
            self.monitor.start(1000)
            self.reconnect()
            self.load_game()

        def t(self,text):
            return translate(text,self.language_code)

        def update_language(self,*_):
            self.language_code = 'en' if self.language.currentIndex()==1 else 'zh'
            for widget,text in self.translatable:
                widget.setText(self.t(text))
            self.sidebar_action.setText(self.t('参数栏'))
            self.pose_action.setText(self.t('3D 姿态'))
            self.gain.setPrefix(self.t('灵敏度  '))
            self.pause_button.setText(self.t('继续输入' if self.pause_button.isChecked() else '暂停输入'))
            self.set_device_status(self.device_status)
            self.set_web_status(self.web_status)

        def set_device_status(self,text):
            self.device_status=text
            self.device_label.setText(self.t(text))

        def set_web_status(self,text):
            self.web_status=text
            self.web_label.setText(self.t(text))

        def activation(self, state):
            self.is_active = state == Qt.ApplicationActive

        def release_device(self):
            if self.device:
                self.device.quit()
                self.device = None

        def reconnect(self):
            if self.child and self.child.state() != QProcess.NotRunning:
                return
            self.release_device()
            try:
                self.driver.prepare()
                self.set_device_status("正在连接 SpaceMouse…")
            except (OSError, ValueError) as e:
                logging.exception("driver prepare")
                self.set_device_status("无法启动官方驱动，请打开 3Dconnexion 设置后重试")
            self.next_scan = time.monotonic() + .4

        def scan(self):
            self.next_scan = time.monotonic() + 2
            try:
                self.device = DriverSpaceMouse.open() if FRAMEWORK.exists() else HIDSpaceMouse.open()
                if self.device:
                    if hasattr(self.device,'set_active'): self.device.set_active(self.is_active)
                    self.set_device_status("● " + self.device.name)
                else:
                    self.set_device_status("未找到 SpaceMouse，请检查连接\n每两秒自动重试")
            except OSError:
                self.set_device_status("设备被占用或无权限\n请点“重新连接设备”重试")

        def load_game(self, *_):
            preset = PRESETS[self.games.currentIndex()]
            self.proc.expo = preset["expo"]
            self.invert.setChecked(preset["invert_rot"])
            self.web.setUrl(QUrl(preset["url"]))

        def load_started(self):
            self.loaded = False
            self.set_web_status("正在加载游戏…")

        def load_finished(self, ok):
            self.loaded = ok
            self.set_web_status("游戏已载入 · 自动连接手柄" if ok else "游戏载入失败，请检查网络后重试")
            if ok:
                self.web.setFocus()
                self.web.pose.raise_()

        def tick(self):
            raw = [0.0] * 6
            child_running = self.child and self.child.state() != QProcess.NotRunning
            if not self.device and not child_running and time.monotonic() >= self.next_scan:
                self.scan()
            if self.device:
                try:
                    self.device.poll()
                    if hasattr(self.device,'set_active'): self.device.set_active(self.is_active)
                    raw = self.device.axes.copy()
                except OSError:
                    self.release_device()
                    self.set_device_status("设备已断开，正在重新连接…")
            self.proc.mode = self.mode.currentText()
            self.proc.pan_gain = self.proc.tilt_gain = self.gain.value()
            self.proc.rot_gain = 1.3 * self.gain.value()
            trans, rot = self.proc.process(raw)
            axes = [anti_deadzone(trans.x,.1), anti_deadzone(-trans.y,.1),
                    anti_deadzone(-rot if self.invert.isChecked() else rot,.1), 0.0]
            paused = self.pause_button.isChecked() or not self.is_active or self.device is None or bool(child_running)
            if paused: axes = [0.0]*4
            self.last_frame = {"a":axes,"b":[0]*17,"paused":paused}
            if self.loaded:
                self.page.runJavaScript("window.__smNativeBridge?.receive?.(" + json.dumps(self.last_frame) + ")")
            for bar, value in zip(self.bars, raw):
                bar.setValue(round(value*100))
                bar.setFormat(f"{value:+.2f}")
            self.web.pose.raw=raw
            if self.pose_action.isChecked():
                self.web.pose.raise_()
                self.web.pose.update()

        def monitor_page(self):
            if self.loaded:
                code = "JSON.stringify({pad:!!window.__smBridge,native:typeof window.__smNativeBridge?.receive==='function',blocked:!!window.__smNativeBridge?.blocked,badge:document.querySelector('[title=\\\"SpaceMouse bridge - click to toggle\\\"]')?.textContent,axes:window.__smBridge?.pad.axes,buttons:window.__smBridge?.pad.buttons.map(b=>b.value),game:!!window.__sim,focused:document.hasFocus()})"
                self.page.runJavaScript(code, self.page_status)
            if args.smoke_test and time.monotonic() - self.started > 90 and not self.smoke_finished:
                self.finish_smoke({"ok":False,"error":"game load timeout"})

        def page_status(self, result):
            try:
                status = json.loads(result) if result else {}
            except ValueError:
                status = {}
            if status.get("native"):
                self.set_web_status("● 菜单中 · 已锁定帽子输入" if status.get("blocked") else "● 虚拟手柄已连接 · 无需书签")
                if args.smoke_test and status.get("game") and self.device is not None:
                    self.finish_smoke({"ok":True,"device":self.device.name, "browser":status,
                                       "frozen":getattr(sys,"frozen",False)})

        def finish_smoke(self, status):
            if self.smoke_finished: return
            self.smoke_finished = True
            args.smoke_test.parent.mkdir(parents=True,exist_ok=True)
            original=(self.language.currentIndex(),self.sidebar_action.isChecked(),self.pose_action.isChecked())
            self.language.setCurrentIndex(1)
            self.sidebar_action.setChecked(False)
            self.pose_action.setChecked(True)
            app.processEvents()
            self.web.pose.raise_()
            self.web.pose.repaint()
            status['ui']={'english':self.reload_button.text()=='Reload game',
                          'sidebar_collapsed':not self.sidebar_scroll.isVisible(),
                          'pose_visible':self.web.pose.isVisible()}
            self.grab().save(str(args.smoke_test.with_suffix('.png')))
            self.pose_action.setChecked(False)
            status['ui']['pose_hides']=not self.web.pose.isVisible()
            self.language.setCurrentIndex(original[0])
            self.sidebar_action.setChecked(original[1])
            self.pose_action.setChecked(original[2])
            status['ok']=bool(status.get('ok') and all(status['ui'].values()))
            args.smoke_test.write_text(json.dumps(status,ensure_ascii=False,indent=2))
            QTimer.singleShot(500,self.close)

        def practice(self):
            if self.child and self.child.state() != QProcess.NotRunning:
                return
            self.release_device()
            self.pause_button.setChecked(True)
            self.child = QProcess(self)
            self.child.finished.connect(self.practice_finished)
            self.child.errorOccurred.connect(self.practice_error)
            argv = ["--simulator"] if getattr(sys,"frozen",False) else [str(resource_path("macos_app.py")),"--simulator"]
            self.child.start(sys.executable,argv)
            self.practice_button.setEnabled(False)
            self.set_device_status("本地练习中 · 按 K 开始校准\n关闭练习窗口后自动返回")

        def practice_finished(self, *_):
            self.proc.cal = Calibration()
            self.practice_button.setEnabled(True)
            self.pause_button.setChecked(False)
            self.next_scan = 0
            self.web.setFocus()

        def practice_error(self, *_):
            self.practice_finished()
            QMessageBox.warning(self,self.t("本地练习"),self.t("无法启动练习窗口，请重新打开 App。"))

        def import_calibration(self):
            filename,_ = QFileDialog.getOpenFileName(self,self.t("选择 calibration.json"),"","JSON (*.json)")
            if not filename: return
            cal = Calibration(filename)
            if not any(cal.data.values()):
                QMessageBox.warning(self,self.t("校准文件"),self.t("此文件没有有效的方向校准数据。"))
                return
            cal.path = str(data_dir / "calibration.json")
            cal.save()
            self.proc.cal = cal
            self.web.setFocus()

        def closeEvent(self, event):
            self.timer.stop()
            self.monitor.stop()
            if self.child and self.child.state() != QProcess.NotRunning:
                self.child.terminate()
                if not self.child.waitForFinished(1500):
                    self.child.kill()
                    self.child.waitForFinished(500)
            self.release_device()
            prefs={"game":PRESETS[self.games.currentIndex()]["key"],"mode":self.mode.currentText(),"gain":self.gain.value(),
                   "language":self.language_code,"sidebar":self.sidebar_action.isChecked(),"pose":self.pose_action.isChecked()}
            try:
                self.settings_file.write_text(json.dumps(prefs,indent=2))
            except OSError:
                logging.exception("save preferences")
            try: self.driver.restore()
            except OSError: logging.exception("driver restore")
            event.accept()

    window = Window()
    window.show()
    result = app.exec()
    lock.unlock()
    if args.smoke_test:
        if not args.smoke_test.exists(): return 1
        return 0 if json.loads(args.smoke_test.read_text()).get("ok") else 1
    return result


if __name__ == "__main__":
    sys.exit(main())
