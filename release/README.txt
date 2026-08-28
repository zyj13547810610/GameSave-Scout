GameSave Scout 0.3.6 Windows x64 完整离线便携版
========================================

运行方式
--------

1. 将 ZIP 完整解压到本地固定磁盘上的可写目录。
2. 保持 GameSaveScout.exe、_internal 和 runtime 的相对位置不变。
3. 双击 GameSaveScout.exe 启动。

本便携版不需要安装 Python、Node.js、Visual Studio 或系统 WebView2 Runtime。
启动和本地管理功能可以离线使用。程序不支持从 UNC、网络共享或网络驱动器运行。
如果希望减小下载和解压体积，可改用名称以 -lite 结尾的轻量联网版；轻量版使用
Windows 中共享的 Evergreen WebView2 Runtime，不包含本目录的 Fixed Runtime。

便携数据
--------

首次正常启动时，GameSave Scout 会在 GameSaveScout.exe 同级创建 data 目录。数据库、配置、
封面、清单、日志、备份和 WebView 用户数据都保存在 data 内。复制或移动便携版前，
请先完全退出 GameSave Scout，并复制整个程序目录。

Windows 10 权限准备
-------------------

Windows 10 使用内置 Fixed Version WebView2 Runtime 前，需要给同级 runtime 目录授予
两个 Windows AppContainer 身份的读取和执行权限。GameSave Scout 会通过系统 icacls.exe
只处理这个 runtime 目录，不申请管理员权限，也不修改其他目录。如果目录不可写，
程序会在创建窗口前停止并给出错误。

故障排查
--------

- 不要单独移动 GameSaveScout.exe，也不要删除或改名 _internal、runtime。
- 确保整个程序目录位于本地固定磁盘且当前用户可以写入。
- 启动失败日志位于 data\logs\startup-error.log。
- 可运行以下命令生成机器可读诊断：

  GameSaveScout.exe --smoke-test --json-output C:\absolute\gamesave-scout-smoke.json

  --json-output 必须是绝对路径。

签名与许可证
------------

GameSave Scout 0.3.6 未进行 Authenticode 代码签名，Windows Defender SmartScreen 可能显示
“Windows 已保护你的电脑”或“未知发布者”。请只使用从可信来源取得且 SHA-256 与发布
记录一致的 ZIP，不要关闭或绕过系统安全功能。

GameSave Scout 使用 MIT License，详见 LICENSE。第三方组件及数据的来源和许可证详见
THIRD_PARTY_NOTICES.md；runtime 原归档中的许可证材料也会原样保留。
