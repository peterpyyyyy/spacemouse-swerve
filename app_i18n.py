"""App UI translations; external games retain their own language."""
EN = {
    '连接 · 操控 · 开始比赛':'Connect · Drive · Play',
    '正在准备设备…':'Preparing device…','正在加载游戏…':'Loading game…',
    '重新载入游戏':'Reload game','暂停输入':'Pause input','继续输入':'Resume input',
    '重新连接设备':'Reconnect device','融合方式':'Input mode','灵敏度  ':'Sensitivity  ',
    '反转旋转方向':'Invert rotation',
    '左右推':'Pan X','前后推':'Pan Y','上下压':'Pan Z','前后倾':'Pitch','左右倾':'Roll','扭转':'Twist',
    '校准 / 本地练习':'Calibrate / practice','导入已有校准':'Import calibration',
    '参数栏':'Settings','3D 姿态':'3D pose',
    '正在连接 SpaceMouse…':'Connecting SpaceMouse…',
    '无法启动官方驱动，请打开 3Dconnexion 设置后重试':'Open 3Dconnexion settings, then retry.',
    '未找到 SpaceMouse，请检查连接\n每两秒自动重试':'SpaceMouse not found. Check the cable.\nRetrying every two seconds.',
    '设备被占用或无权限\n请点“重新连接设备”重试':'Device busy or access denied.\nClick Reconnect device to retry.',
    '设备已断开，正在重新连接…':'Device disconnected. Reconnecting…',
    '游戏已载入 · 自动连接手柄':'Game loaded · connecting gamepad',
    '游戏载入失败，请检查网络后重试':'Could not load game. Check your network.',
    '● 虚拟手柄已连接 · 无需书签':'● Gamepad connected · no bookmark needed',
    '● 菜单中 · 已锁定帽子输入':'● In menu · cap input locked',
    '本地练习中 · 按 K 开始校准\n关闭练习窗口后自动返回':'Practice open · press K to calibrate.\nClose it to return to the game.',
    '本地练习':'Local practice','无法启动练习窗口，请重新打开 App。':'Could not launch practice. Reopen the app.',
    '选择 calibration.json':'Select calibration.json','校准文件':'Calibration file',
    '此文件没有有效的方向校准数据。':'This file has no valid direction calibration.',
    '点击游戏画面后使用键盘\nJ 吸球  ·  K 射球\nL 传球  ·  ; 吐球\n\n使用官方驱动接入，退出后恢复 CAD 控制':
    'Click the game to use the keyboard.\nJ Intake · K Shoot\nL Pass · ; Eject\n\nOfficial driver stays running. CAD control returns when the app closes.',
}


def translate(text, language):
    return EN.get(text,text) if language == 'en' else text
