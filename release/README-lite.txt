GameShelf 0.1.0 Windows x64 轻量联网便携版
========================================

运行方式
--------

1. 将 ZIP 完整解压到本地固定磁盘上的可写目录。
2. 保持 GameShelf.exe、_internal 和 prerequisites 的相对位置不变。
3. 双击 GameShelf.exe 启动。

本版本不包含 WebView2 Fixed Version Runtime，而是使用 Windows 中共享的 Evergreen
WebView2 Runtime。系统已经安装 Evergreen 时，GameShelf 可以断网启动。系统缺失
Evergreen 时，GameShelf 会先询问是否联网安装；只有选择“是”后，才会运行随包的
微软官方安装器。安装成功后由当前 GameShelf 进程继续启动，不会再创建第二个
GameShelf 进程。

取消与安装失败
--------------

- 选择“否”会直接取消本次启动，不写错误堆栈。
- 断网、安装器损坏或安装失败时，诊断信息写入
  data\logs\startup-error.log。
- 删除整个 GameShelf 目录不会卸载系统共享的 Evergreen WebView2 Runtime。

便携数据
--------

首次正常启动时，GameShelf 会在 GameShelf.exe 同级创建 data 目录。数据库、配置、
封面、清单、日志、备份和 WebView 用户数据都保存在 data 内。复制或移动便携版前，
请先完全退出 GameShelf，并复制整个程序目录。

故障排查
--------

- 不要单独移动 GameShelf.exe，也不要删除或改名 _internal、prerequisites。
- 确保整个程序目录位于本地固定磁盘且当前用户可以写入。
- 可运行以下命令生成机器可读诊断；该命令不会运行安装器：

  GameShelf.exe --smoke-test --json-output C:\absolute\gameshelf-smoke.json

签名与许可证
------------

GameShelf 0.1.0 本体未进行 Authenticode 代码签名。随包
MicrosoftEdgeWebview2Setup.exe 是微软官方签名的 Evergreen Bootstrapper；请勿替换。
GameShelf 使用 MIT License，第三方来源和许可证详见 THIRD_PARTY_NOTICES.md。
