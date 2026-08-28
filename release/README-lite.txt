GameSave Scout 0.3.6 Windows x64 轻量联网便携版
========================================

运行方式
--------

1. 将 ZIP 完整解压到本地固定磁盘上的可写目录。
2. 保持 GameSaveScout.exe、_internal 和 prerequisites 的相对位置不变。
3. 双击 GameSaveScout.exe 启动。

本版本不包含 WebView2 Fixed Version Runtime，而是使用 Windows 中共享的 Evergreen
WebView2 Runtime。系统已经安装 Evergreen 时，GameSave Scout 可以断网启动。系统缺失
Evergreen 时，GameSave Scout 会先校验随包的微软官方安装器，并询问是否打开安装位置。
选择“是”后，程序只会打开 prerequisites 文件夹并选中
MicrosoftEdgeWebview2Setup.exe，随后正常退出。请手动双击该安装器联网完成安装，
然后重新启动 GameSave Scout。

GameSave Scout 不会静默运行或等待安装器，也不会自动重新启动自身。

取消与安装失败
--------------

- 选择“否”会直接取消本次启动，不写错误堆栈。
- 微软安装器断网或安装失败时，由安装器自身提示；重新启动后 Runtime 仍缺失时，
  GameSave Scout 会再次显示手动安装引导，不会记录为程序崩溃。
- 随包安装器缺失、SHA-256 不匹配或无法打开安装位置时，诊断信息写入
  data\logs\startup-error.log。
- 删除整个 GameSave Scout 目录不会卸载系统共享的 Evergreen WebView2 Runtime。

便携数据
--------

首次正常启动时，GameSave Scout 会在 GameSaveScout.exe 同级创建 data 目录。数据库、配置、
封面、清单、日志、备份和 WebView 用户数据都保存在 data 内。复制或移动便携版前，
请先完全退出 GameSave Scout，并复制整个程序目录。

故障排查
--------

- 不要单独移动 GameSaveScout.exe，也不要删除或改名 _internal、prerequisites。
- 确保整个程序目录位于本地固定磁盘且当前用户可以写入。
- 可运行以下命令生成机器可读诊断；该命令不会显示提示、打开安装位置或运行安装器：

  GameSaveScout.exe --smoke-test --json-output C:\absolute\gamesave-scout-smoke.json

签名与许可证
------------

GameSave Scout 0.3.6 本体未进行 Authenticode 代码签名。随包
MicrosoftEdgeWebview2Setup.exe 是微软官方签名的 Evergreen Bootstrapper；请勿替换。
GameSave Scout 使用 MIT License，第三方来源和许可证详见 THIRD_PARTY_NOTICES.md。
