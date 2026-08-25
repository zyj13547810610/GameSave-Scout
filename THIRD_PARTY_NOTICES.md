# 第三方组件与数据声明

本文件按 GameSave Scout 0.3.3 Windows x64 候选包中的实际内容核对。各组件仍归其原作者所有，并适用各自许可证；版本升级或冻结环境变化后必须重新审计。

## Python 应用与冻结运行时

| 组件 | 随包版本 | 许可证 | 来源 |
| --- | --- | --- | --- |
| CPython | 3.12.13 | Python-2.0 | https://www.python.org/ |
| PyInstaller bootloader | 6.22.1 | GPL-2.0-or-later，附带允许分发生成程序的 bootloader exception | https://pyinstaller.org/ |
| pywebview | 6.2.1 | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| Microsoft WebView2 SDK binaries | 1.0.3856.49 | Microsoft 软件许可条款 | https://developer.microsoft.com/microsoft-edge/webview2/ |
| pythonnet | 3.1.0 | MIT | https://github.com/pythonnet/pythonnet |
| clr-loader | 0.3.1 | MIT | https://github.com/pythonnet/clr-loader |
| Bottle | 0.13.4 | MIT | https://github.com/bottlepy/bottle |
| CFFI | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| proxy_tools | 0.1.0 | MIT | https://github.com/jtushman/proxy_tools |
| setuptools | 84.0.0 | MIT | https://github.com/pypa/setuptools |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| wheel | 0.48.0 | MIT | https://github.com/pypa/wheel |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| Pillow | 12.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| RapidFuzz | 3.14.5 | MIT | https://github.com/rapidfuzz/RapidFuzz |
| pefile | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |

## CPython 随附原生库

这些库由受控 Conda Windows x64 前缀提供，并作为 CPython 扩展的实际运行时依赖随包分发。

| 组件 | 随包版本 | 许可证 | 来源 |
| --- | --- | --- | --- |
| bzip2 | 1.0.8 | bzip2-1.0.6 | https://sourceware.org/bzip2/ |
| Expat / libexpat | 2.8.1 | MIT | https://github.com/libexpat/libexpat |
| libffi | 3.7.0 | MIT | https://github.com/libffi/libffi |
| liblzma / XZ Utils | 5.8.3 | 0BSD | https://tukaani.org/xz/ |
| OpenSSL | 3.6.3 | Apache-2.0 | https://www.openssl.org/ |
| SQLite | 3.53.4 | Public Domain blessing | https://www.sqlite.org/ |
| zlib | 1.3.2 | Zlib | https://zlib.net/ |
| Microsoft Universal CRT | 10.0.26100.0 | Microsoft Windows SDK 许可条款 | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |
| Microsoft Visual C++ Runtime | 14.51.36247 | Microsoft Visual C++ Redistributable 许可条款 | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

## 前端运行时

| 组件 | 随包版本 | 许可证 | 来源 |
| --- | --- | --- | --- |
| Vue.js（含 @vue/runtime、reactivity、shared） | 3.5.41 | MIT | https://github.com/vuejs/core |
| Pinia | 3.0.4 | MIT | https://github.com/vuejs/pinia |
| @vue/devtools-api、kit、shared | 7.7.10 | MIT | https://github.com/vuejs/devtools |
| birpc | 2.9.0 | MIT | https://www.npmjs.com/package/birpc |
| hookable | 5.5.3 | MIT | https://www.npmjs.com/package/hookable |
| mitt | 3.0.1 | MIT | https://www.npmjs.com/package/mitt |
| perfect-debounce | 1.0.0 | MIT | https://www.npmjs.com/package/perfect-debounce |
| speakingurl | 14.0.1 | BSD-3-Clause | https://www.npmjs.com/package/speakingurl |
| superjson | 2.2.6 | MIT | https://www.npmjs.com/package/superjson |
| copy-anything | 4.0.5 | MIT | https://www.npmjs.com/package/copy-anything |
| is-what | 5.5.0 | MIT | https://www.npmjs.com/package/is-what |
| rfdc | 1.4.1 | MIT | https://www.npmjs.com/package/rfdc |

Vite、Vitest、TypeScript、vue-tsc 和 jsdom 仅参与构建或测试，不进入最终静态资源，因而不列为随包运行时组件。

## Ludusavi Manifest

- 项目：https://github.com/mtkennerly/ludusavi-manifest
- 用途：提供 PC 游戏存档及配置位置的离线规则快照
- 许可证：MIT
- 随附许可证：`_internal/resources/manifests/ludusavi/LICENSE`

GameSave Scout 只读取这些位置规则来生成待用户确认的建议，不使用 Ludusavi 执行备份或恢复。

## Microsoft Edge WebView2 Fixed Version Runtime

- 版本：151.0.4129.86 x64
- 来源：https://developer.microsoft.com/microsoft-edge/webview2/
- 用途：提供离线、固定版本的 Edge Chromium WebView2 运行时
- 原始运行时文件完整保留；其内部第三方许可证入口 `runtime/show_third_party_software_licenses.bat` 及随附的组件许可证文件未被裁剪

## Microsoft Edge WebView2 Evergreen Bootstrapper

- 来源：https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section
- 发布文件名：`prerequisites/MicrosoftEdgeWebview2Setup.exe`
- 用途：仅在轻量联网版检测不到系统共享 Evergreen WebView2 Runtime、且用户明确同意后，联网安装微软官方运行时
- 该文件由 Microsoft Corporation 签名并按发布受控配置复核版本和 SHA-256；它不是 GameSave Scout 自有二进制
- 安装后的 Evergreen Runtime 属于系统共享组件，删除 GameSave Scout 目录不会将其卸载

本声明不改变任何第三方许可。各项目的完整许可文本、版权声明和例外条款以随附文件及上表来源为准。
