# SpaceMouse Swerve

用 3Dconnexion SpaceMouse 开 FRC swerve 底盘：想看看 6 自由度的输入设备有没有比手柄更好的操控手感。

包含两个程序：

| 程序 | 作用 |
|---|---|
| `swerve_sim.py` | 本地 swerve 手感模拟器（俯视场地 + SpaceMouse 3D 姿态 + 定位挑战），以及**方向校准向导** |
| `spacemouse_bridge.py` | 把 SpaceMouse 变成浏览器里的**虚拟 Xbox 手柄**，用来玩网页版 FRC 模拟器（如 [REBUILT Sim 2026](https://tylerhandel.github.io/rebuilt-sim-2026/)、[frc4206.com](https://www.frc4206.com/)） |

纯 Python + pygame，支持 **Windows / macOS**（Linux 理论可用）。

新增 [macOS 集成 App](https://github.com/peterpyyyyy/spacemouse-swerve/releases/tag/v1.0.0-beta.1)：内置游戏、中英文菜单、可折叠参数栏及可隐藏的实时 3D 姿态，使用方法见下方“macOS 集成 App”。

## 安装运行

需要 Python 3.9+。

**macOS**：双击 `run_bridge.command`（桥接）或 `run_sim.command`（本地模拟器）。
首次运行会自动建 `.venv` 并安装依赖。
- 如果提示“无法打开/来自身份不明的开发者”：右键 → 打开；或在终端执行
  `chmod +x *.command && xattr -dr com.apple.quarantine .`
- 没有 Python：`xcode-select --install`，或从 python.org 安装。

**Windows**：双击 `run_bridge.bat` / `run_sim.bat`。

**手动**：
```bash
python3 -m pip install -r requirements.txt
python3 swerve_sim.py          # 本地模拟器
python3 spacemouse_bridge.py   # 浏览器桥接
```

## 输入处理（两个程序共用）

SpaceMouse 帽子既能**推**（pan）也能**倾斜**（tilt），人手推的时候两者几乎必然混在一起。
处理流程：方向校准 → 动态死区解耦（扭转时抑制平移泄漏，反之亦然）→ pan/tilt 融合 → 轴吸附（可选）→ expo。

融合模式（数字键 1-5）：

| 模式 | 说明 |
|---|---|
| PAN | 只用推 |
| TILT | 只用倾斜 |
| **FUSE**（默认） | 方向 = pan+tilt 的合向量，幅值 = 两者较大值，不会叠加超速 |
| SUM | 直接相加（对照组） |
| DOMINANT | 取较大的源，带迟滞 |

**第一次用先做校准**：在 `swerve_sim.py` 里按 `K`，按提示依次往 前/右/后/左 推、再倾斜，
结果存到 `calibration.json`，桥接程序会自动加载。（每台设备、每个人手法不同，所以不进仓库。）

## swerve_sim.py 按键

| 键 | 功能 |
|---|---|
| K / L | 校准向导 / 开关校准 |
| 1-5 | 融合模式 |
| G | 轴吸附 ±15° |
| F | field / robot oriented |
| C | 动态死区解耦 |
| 7 8 / 9 0 | 扭转灵敏度 / 旋转最大速度 |
| [ ] / ; ' | 死区 / expo |
| N M / , . | pan 增益 / tilt 增益 |
| - = | 速度上限 |
| I O | 反转 pitch / roll |
| T / X | 定位挑战 / 清空成绩 |
| Z / Space / Tab / H / Esc | 航向归零 / 重置 / 键盘↔SpaceMouse / 帮助 / 退出 |

## 浏览器桥接

1. 运行 `spacemouse_bridge.py`，浏览器打开 <http://127.0.0.1:8765/>。
2. 把绿色按钮拖到书签栏（Windows `Ctrl+Shift+B` / Mac `Cmd+Shift+B` 显示书签栏）。
   书签只是个加载器，代码从本机桥接加载，更新后不用重新拖。
3. 打开模拟器页面，点书签，左下角出现 `● SM` 即连接成功。
   浏览器若询问“允许访问本地网络/设备”，选**允许**（Chrome/Edge 的 Local Network Access）。
4. 再点一次书签或徽标 = 关闭。

映射：左摇杆 = 平移，右摇杆 X = 旋转。SpaceMouse 自带按键**不映射**（按下会晃动帽子，还会弹出 3Dconnexion 菜单）。
左手 SpaceMouse，右手键盘：

| 键 | 手柄按键 | REBUILT Sim 2026 |
|---|---|---|
| J | LT | 吸球 |
| K | RT | 射球 |
| L | RB | 传球 |
| ; | LB | 吐球 |

桥接窗口按键：`P` 切换模拟器预设（REBUILT / frc4206，后者的 3D 视图旋转是镜像的，预设已反转），
`V` 临时反转旋转，`- =` 反死区（抵消网页模拟器自带的 0.1 死区），`Space` 暂停输出，`R` 重新扫描设备，其余同上。

推荐 Chrome / Edge。Safari 未测试。
J/K 等按键需要浏览器游戏页面获得焦点；吸球和射球需在游戏允许手动操作的阶段使用。

## macOS 集成 App（推荐）

双击 `SpaceMouse Swerve.app`，自动连接设备并在内置浏览器中载入游戏，无需终端、书签或浏览器扩展。

- 保持官方 3DxWare / `3DconnexionHelper` 运行。App 通过官方接口读取，正常退出后让出设备给 CAD。
- 顶部“参数栏”可折叠左栏，“3D 姿态”可隐藏/显示角落的实时设备姿态；右上角切换中文或 English。
- 在 REBUILT 的菜单、设置、暂停和结算界面锁定 SpaceMouse 帽子输入，使用鼠标选菜单；只在比赛画面接收控制。
- App 失去前台焦点、暂停、设备断开时归零。J/K/L/分号分别为吸球、射球、传球、吐球，游戏画面需获得键盘焦点。
- “校准 / 本地练习”打开原生模拟器，按 K 校准，关闭后回到游戏。App 数据保存于 `~/Library/Application Support/SpaceMouse Swerve`。
- 本次打包面向 Apple Silicon / macOS 14+，已做本地 ad-hoc 签名，未做 Apple 开发者签名或公证。蓝牙和 Intel 构建未验证。
- 集成版包含 Python 和 Chromium，源码运行/构建方法见 [英文 README](README.md)。独立脚本仍可使用。

请不要再沿用早期“关闭 3DconnexionHelper”的操作。官方已说明，退出它可能使 SpaceMouse 直接移动 macOS 光标：
https://3dconnexion.com/us/support/faq/my-spacemouse-moves-the-mouse-cursor-on-macos/

## 文件

```
swerve_sim.py          本地模拟器 + 共用的输入处理 / 3D 视图
spacemouse_hid.py      macOS 直接 HID 读取（SDL 未识别时自动回退）
spacemouse_bridge.py   WebSocket 桥接 (ws://127.0.0.1:8765/ws) + 状态窗口
spacemouse_gamepad.js  注入网页的虚拟手柄 (覆盖 navigator.getGamepads)
run_*.command / .bat   一键启动脚本
```

Mac 实测结果与复查命令见 [MACOS_VALIDATION.md](MACOS_VALIDATION.md)。
