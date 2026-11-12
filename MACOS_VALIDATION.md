# macOS 验证记录

日期：2026-11-12。

## 环境

- Apple Silicon（arm64），macOS 27.2.1。
- Python 3.13.1、pygame 2.6.1（SDL 2.28.4）、websockets 17.4、hidapi 0.15.0。
- SpaceMouse Wireless BT，USB 连接，VID/PID `256f:c63a`。
- Chromium 浏览器，REBUILT Sim 2026。

## 结果

- `git fsck --full` 通过，源文件齐全。下载目录内的两个 `.command` 文件原为 CRLF 且无执行权限，已改为 LF 并恢复执行权限。Git 中已有 LF 和可执行标记。
- 首次检测到设备但 SDL 无摇杆，HID 也无法打开。退出 `3DconnexionHelper` 后 SDL 和直接 HID 均可打开设备。验证结束后玩模拟器时应继续退出该后台程序，使用 CAD 前可重新启动它。
- 记录了用户实际操作产生的 880 条六轴 HID 报告，六轴均有正负响应、最大绝对值均达到 350，松手后归零。这里验证的是 USB 连接，未测试蓝牙或无线接收器。
- 本地模拟器通过 240 帧自检；把实测输入回放至生产输入处理、底盘模型和渲染流程，确认平移与旋转均有响应，中文界面显示正常。
- 强制跳过 SDL 枚举时，新增的 macOS HID 回退可打开实物设备；协议测试覆盖六轴合并报告、三轴拆分报告、符号、量程、按钮、归零和输入超时。
- HTTP 首页和脚本返回 200，未知路径返回 404；WebSocket 正常发送 4 轴、17 按钮数据及保活。
- 浏览器允许本地网络连接后，网页显示 `● SM` 并识别标准布局的 SpaceMouse 虚拟 Xbox 手柄。实物操作实时到达游戏，测得 LX/LY/RX 峰值分别为 1.0/1.0/0.8547，松手后归零；用户确认游戏内操控正常。
- J/K/L/分号映射、松键、关闭/开启虚拟手柄通过。游戏内部也实测到 J → `lt=1, intake=true`，K → `rt=1, shoot=true`（teleop 阶段）；用户确认 J/K 有反应。
- 额外修正浏览器失联或数据停滞时仍保留键盘按钮的问题；回归检查确认平移、旋转和按键均归零，失联期间键盘不继续触发虚拟按钮。

## 复查

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
node tests/test_gamepad.cjs    # 可选：此回归检查需要 Node.js，程序运行不需要
bash -n run_bridge.command
bash -n run_sim.command
./run_sim.command --selftest 240
./run_bridge.command --selftest 240
```

真实设备验证不能用合成自检替代。测试时先退出 3DconnexionHelper，保持游戏页面获得焦点，并允许浏览器访问本机桥接。

未验证 Safari、Windows、Linux、所有机器人/游戏模式，以及蓝牙连接。第三方网页有可选资源 404，但本次游戏及手柄输入流程正常。个人校准和桥接偏好文件不提交到仓库。
