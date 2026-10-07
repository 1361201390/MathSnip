# MathSnip

Windows 10/11 的轻量公式截图工具：快捷键框选 → Mathpix API → 自动复制 LaTeX。

看论文、读 PDF 或网页时，按 **Alt+Q** 框选公式，松开鼠标后 LaTeX 就已经在剪贴板里，直接粘贴到 LaTeX 编辑器、Markdown 笔记或 Word 中。

- **一键识别**：全局快捷键框选，结果自动复制，不弹窗抢焦点。
- **三种输出**：纯 LaTeX、`$$` 块公式（Markdown）、Word LaTeX 输入。
- **自带密钥**：使用你自己的 Mathpix API 凭据，Windows DPAPI 加密保存在本机。
- **不留痕迹**：截图只在内存中处理，不保存截图和识别历史。
- **省钱设计**：失败不自动重试，避免重复计费；多显示器、高 DPI 均可用。

> 需要自行注册 Mathpix API 并开通计费，本工具不附带任何免费额度。

## 开始使用

1. 安装 **Python 3.12 64 位**，安装时勾选 Python Launcher 和 Add Python to PATH。下载：<https://www.python.org/downloads/windows/>。
2. `git clone` 本仓库，或点击 **Code → Download ZIP** 解压到固定位置，例如 `D:\Tools\MathSnip`。
3. 双击 **run.bat**。首次启动会创建独立环境并下载依赖，需要联网；后续启动直接进入工具。
4. 设置页填写 Mathpix **App ID** 和 **API Key**，点击“保存设置”。凭据来自 <https://console.mathpix.com/>，请先在控制台开通 API 计费。
5. 点击“收起到托盘”，打开包含公式的 PDF 或网页，按 **Alt+Q** 并拖动框选。松开后识别，结果自动复制，按 Ctrl+V 即可粘贴。

设置不会验证账号或调用付费 API，第一次框选才发送请求。你不需要把 API Key 发给任何人。

## 快捷键

| 默认快捷键 | 输出 | 粘贴位置 |
| --- | --- | --- |
| Alt+Q | 不带外层数学定界符的 LaTeX | LaTeX 编辑器、支持公式输入的应用 |
| Alt+W | `$$` 包裹的块公式 | 支持数学公式的 Markdown 编辑器 |
| Alt+E | 不带定界符的 LaTeX，显示 Word 操作提示 | Word 的 LaTeX 公式输入框 |

快捷键可以在设置页改为 `Ctrl+Shift+Q` 等组合。支持 Ctrl / Alt / Shift / Win 加 A–Z、0–9、F1–F24。如果被其他程序占用会提示，保存失败会恢复原快捷键。

- **Esc 或右键**：取消框选，不调用 API，也不改动剪贴板。
- 支持多个显示器和缩放比例；每次框选限制在同一个显示器内，不支持跨屏拼接。
- 识别失败保留原剪贴板。识别中忽略新的截图请求，防止重复调用。
- 托盘右键可打开最近结果、设置或退出。双击图标打开结果。关闭窗口会收起到托盘。
- 结果可以手工修改，再点击相应复制按钮，**不会再次请求 API**。
- 成功识别只显示通知，不弹出窗口抢走当前应用焦点。点击通知查看结果。

## Word 使用方法

Alt+E 的内容仍然是 LaTeX 文本，**不是自动生成的 Word 原生 OMML 公式**。

在支持 LaTeX 输入的桌面 Word 中：

1. 按 **Alt+=** 插入公式框。
2. 在“公式”选项卡中将输入格式设为 **LaTeX**。
3. Ctrl+V 粘贴，然后使用“转换 → 专业格式”。

Word 对 LaTeX 支持有范围限制，复杂数组、宏命令和某些环境可能需要手动修改；旧版 Word 可能没有 LaTeX 输入模式。不要在普通正文中粘贴并期待自动生成公式。

## 打包成 EXE

在 Windows 中双击 **build.bat**。脚本安装依赖、运行离线测试，再用 PyInstaller 打包，输出：

```text
dist\MathSnip.exe
```

以后直接双击 EXE，无需 Python 或命令行。EXE 含 Qt 运行库，体积会明显大于源码；单文件启动时需要短暂解压。初次配置仍需填写自己的 API 凭据。不要把 `settings.json` 或真实凭据塞进安装包。

也可以不在本机打包：在本仓库的 **Actions → Build Windows EXE** 中手动运行（推送 `v*` 标签时也会自动运行），完成后在运行页面下载 `MathSnip-Windows` 构建产物。工作流不需要 API 密钥，也不会发送识别请求。

## 凭据与数据

- API Key 经 **Windows DPAPI** 加密后保存到 `%LOCALAPPDATA%\MathSnip\settings.json`，绑定当前 Windows 账户；App ID、快捷键等设置为普通 JSON。工具运行时需在内存中解密密钥。
- 截图仅在内存中处理，只有框选区域发送到固定地址 `https://api.mathpix.com/v3/text`。程序不保存截图、识别日志或持久历史，只保留本次运行中的最近结果。
- 请求使用 `metadata.improve_mathpix=false`。Mathpix 服务端的数据处理与保留规则以其官方文档及账号设置为准；云端 OCR 并不是完全本地识别。
- 调用通过 HTTPS；禁止跟随重定向，不向第三方 OCR 服务转发。`requests` 会遵循当前进程的 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量，不会自动读取所有 Windows 系统代理设置。
- 网络超时或报错**不自动重试**，避免重复计费；即使客户端超时，服务器也可能已经处理并计费。
- API 费用、最低充值、账单规则和配额以控制台为准。工具不包含免费的 Mathpix API 额度；Snip 会员与 API 计费是分别配置的产品。

删除本机配置：先从托盘退出，再删除 `%LOCALAPPDATA%\MathSnip`。卸载程序可删除解压目录与配置目录。加密后的配置不能直接搬到另一个 Windows 账户使用。

## 常见问题

**没有窗口？** 已配置时默认在托盘运行，请展开任务栏右侧隐藏图标；重复启动会提示已有实例。

**双击 run.bat 没反应？** 之前的版本会用 `pythonw.exe` 静默启动，环境有问题时窗口和报错都会一起消失。现在 run.bat 会先用带控制台的方式导入整个程序：失败时会把原因打印出来并停在窗口里，同时写入 `startup-error.log`。最常见的原因是借用了 **Anaconda 的 Python** 建 `.venv`：Anaconda 会把自带的 `Library\bin\icuuc.dll`（ICU 73，只导出 `ucnv_open_73` 这类带版本号的符号）放在 DLL 搜索路径前面，而 Qt 需要 `System32\icuuc.dll` 里的无版本号符号，于是报 `DLL load failed while importing QtCore: The specified procedure could not be found.`。程序启动时会自动先绑定系统 ICU 再导入 Qt（`qt_loader.py`），这类环境无需处理；如果仍然失败，删除 `.venv` 文件夹后重新运行 `setup.bat`。

**快捷键被占用？** 设置页换成 `Ctrl+Shift+Q / W / E`，检查其他截图工具。

**认证失败或额度不足？** 检查 App ID、API Key、API 计费状态和配额。Mathpix 网页登录密码不能作为 API Key。

**提示「TLS 握手被中断」或连不上 `api.mathpix.com`？** 这两种情况都发生在请求发出去之前，所以**不会计费**，直接重新框选即可；只有「等待响应超时」才可能已经计费。它们几乎都是代理链路问题，与账号、额度无关。先在终端跑一句确认链路：

```powershell
.venv\Scripts\python.exe -c "import requests; print(requests.get('https://api.mathpix.com/v3/text', timeout=(8, 20)).status_code)"
```

返回 `401` 就是通的（401 = 没带凭据的正常结果）。如果 DNS 把 `api.mathpix.com` 解析成 `198.18.x.x`，说明你正走 Clash/Surge 的 **fake-IP + TUN 模式**：请确认规则里 `api.mathpix.com` 走的是代理节点而不是 DIRECT，节点不稳定时会出现「时通时断」。也可以在启动前显式指定代理端口：

```bat
set HTTPS_PROXY=http://127.0.0.1:7890
run.bat
```

`requests` 只读 `HTTP_PROXY / HTTPS_PROXY` 环境变量，**不会**读取 Windows「Internet 选项」里的系统代理，所以浏览器能开 Mathpix 网页不代表程序一定走同一条路。

**截图偏移或黑屏？** 在正常 Windows 桌面内使用，检查缩放比例、远程桌面和窗口保护；受保护的视频或桌面不能保证可捕获。

**需要开机启动？** 打包后按 Win+R 输入 `shell:startup`，把 EXE 的快捷方式放进去。源码模式可把 run.bat 的快捷方式放进去，保留整个源码目录和 `.venv`。程序不会自行设置开机启动。

**如何排查启动异常？** 直接双击 `run.bat` 看它打印的原因，或在本目录的终端运行 `.venv\Scripts\python.exe mathsnip.py`。崩溃时程序还会把 traceback 写到 `%LOCALAPPDATA%\MathSnip\error.log` 并弹出对话框。不要发送包含凭据的设置文件。

## 开发与验证

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe mathsnip.py
```

测试覆盖请求参数、错误响应、无自动重试、输出格式、快捷键冲突回滚、不同 DPI 裁剪、剪贴板保留、取消操作、线程数据释放。Windows 上还会运行 DPAPI 加密往返测试，其他平台跳过它。测试使用模拟响应，不访问 Mathpix。

自动化测试**不调用真实付费 API**；全局快捷键、多屏原生捕获和 Word 转换无法自动化测试，需要在真实 Windows 桌面上手动验证。首次使用建议先识别一张小公式确认流程正常。欢迎提交 Issue 和 Pull Request。

实现直接调用官方 REST API，避免为一个图像请求引入完整 SDK。官方参考：

- 图像 OCR：<https://docs.mathpix.com/reference/post-v3-text>
- 官方 Python SDK：<https://github.com/Mathpix/mpxpy>
- PyInstaller 平台打包说明：<https://pyinstaller.org/en/stable/operating-mode.html>

源码使用 MIT 许可证。PySide6、Qt 和 requests 等依赖分别受各自许可证约束；再分发 EXE 时需遵循其许可证并保留相应通知。
