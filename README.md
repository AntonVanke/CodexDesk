# Codex Desk

Windows 桌面应用 + DA14585 蓝牙状态屏。查看 Codex 剩余额度、重置时间、正在进行的任务、待回答问题和未读对话。

[下载 Windows 应用与屏幕固件](https://github.com/AntonVanke/CodexDesk/releases/latest)

## 使用

1. 在 Windows 电脑上安装并登录 Codex，打开蓝牙。
2. 下载并运行 `CodexDesk.exe`。
3. 屏幕未连接时显示下载二维码和配对码，例如 `A1B2C3-123456`。
4. 在应用中输入完整配对码，点击「连接」。应用自动寻找屏幕并完成加密配对。

数据变化后按需推送；「手动同步」用于主动刷新。应用常驻右下角系统托盘，不占任务栏；窗口关闭或最小化后收起到托盘，右键托盘图标选择「退出应用」完全退出。

应用启动后及每隔 6 小时自动检查 GitHub 上的应用和固件版本，只提示可用更新。可在设置中手动检查、前往 Release 下载，再手动安装应用或选择固件升级。每次发布均同步源码、应用、固件和版本清单到 GitHub。

右上角设置包含画面亮度、屏幕样式、开机启动、解除配对和固件升级。「屏幕样式」支持基础样式、任务动态、白天/黑夜/跟随系统和强调色。用户名默认跟随 Codex 账号，也可自定义。切换 Codex 账号后，应用会更新用户名、额度和当前账号的任务列表。

任务总览同时显示运行任务、待回答问题和未读对话。阅读 Codex 中的未读对话后，该对话会随原生已读状态更新。提问与总览交替轮播。

## 换电脑与解绑

屏幕仅保存一台电脑的蓝牙绑定。原电脑可用时，在设置中点击「解除配对」；原电脑不在时，使用屏幕当前显示的配对码在新电脑配对。新绑定替换原绑定。配对 PIN 在断开后更新；已绑定电脑通过保存的蓝牙密钥自动重连。

配对码前六位是设备编号，后六位是蓝牙 PIN。广播只包含设备编号。数据与固件升级服务需要经过认证的加密连接。

## 硬件

- AESL0240TC 二手屏，DA14585，320 × 240 LCD。
- 512 KiB SPI Flash，双镜像 SUOTA 无线升级。
- 配置存储：`0x7E000`；蓝牙绑定存储：`0x7F000`。
- 本固件的引脚和 LCD 初始化对应上述屏幕。

额度颜色：大于 70% 绿色，50–70% 黄色，20–50% 橙色，低于 20% 红色。

## 桌面应用构建

需要 Windows、Python 3.12：

```powershell
python -m pip install -r requirements-dev.txt
cd codex_status
python -m PyInstaller --noconfirm CodexDesk.spec
```

打包前将 Release 中的 `codex_status.img` 放入 `codex_status/build/`，或先自行构建固件。输出为 `codex_status/dist/CodexDesk.exe`。

## 固件构建

自行安装 Renesas DA145xx SDK 6.0.22.1401 和 LLVM Embedded Toolchain for Arm 17.0.1：

```powershell
$env:RENESAS_SDK = 'D:\SDK\6.0.22.1401'
$env:ARM_LLVM = 'D:\Tools\LLVMEmbeddedToolchainForArm-17.0.1-Windows-x86_64'
python codex_status/build.py
```

输出 `codex_status/build/codex_status.img`，在桌面应用的固件菜单中选择即可无线升级。首次安装本项目固件需要 SWD；之后通过应用升级。

SDK 本体未包含在仓库中。SDK 配置和链接脚本保留原版权声明。

## 数据来源

额度来自本机 Codex app-server 的 `account/rateLimits/read`。任务、提问和未读状态来自本机 Codex 会话记录和已读回执。账号凭据只由本机 Codex 使用；应用不会上传凭据或会话内容到 GitHub。
