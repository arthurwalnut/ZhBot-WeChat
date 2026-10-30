# 第三方来源与许可

## v0.2.7 Wordle 数据增补

按用户指定，从 [andifathulms/word-space](https://github.com/andifathulms/word-space/tree/6b2ce3432d5753d2b77724e0255ca6d4d019d34d/data) 固定提交 `6b2ce3432d5753d2b77724e0255ca6d4d019d34d` 的 `data/answers.txt`（2,315 词）与 `data/guesses.txt`（12,972 词）合并普通五字母词条，未复制其应用代码或界面。原有其他长度词库保留。

核查时该仓库未提供明确开源许可证；未将这份数据标注为 MIT、Apache 或公有领域。其 [data/README.md](https://github.com/andifathulms/word-space/blob/6b2ce3432d5753d2b77724e0255ca6d4d019d34d/data/README.md) 声明来源为 Josh Wardle 原 Wordle 词表、经 cfreshman 镜像取得，并说明其非商业作品集用途；这是上游来源说明。与原项目、作者及商标权利人无隶属关系。

来源摘要：answers.txt SHA-256 `f40e47975cf360ff9febe7d49c8e285054d8fa3fb9644cea575922060951d6ee`；guesses.txt SHA-256 `feacc549249b5dcb43e2799fbbcda14ebc33d55904fb15d043779104e60c1579`。来源说明随包保存在 `src/wordle/word_space.NOTICE`，迁移清单为 `word_space_upgrade.json`。

## v0.2.6 非好友群成员名称补充

`src/wechat_bot/adapters/member_names.py` 移植自 helper 提交
[`7302da4721ee87199d7828a134a3d7ac846799d1`](https://github.com/Prometheus-first/helper/commit/7302da4721ee87199d7828a134a3d7ac846799d1)
中 `wxbot_framework/contacts.py` 的非好友 LRU 名称读取函数。原始完整许可及第三方声明分别随源码保留为 `helper_names.LICENSE`、`helper_names.NOTICE`，同时包含于 wheel、源码包及 Windows ZIP。该文件遵循 `LicenseRef-helper-noncommercial-1.0`。

本地修改：改为从固定 helper 导入读取工具；在上游仅支持 4.2.0.11 的基础上，补入本机实际核验的 4.1.15.56。后者按原生成员 ID 检索已注明的缓存、复核对象 ID 并双读结构，已取得实际非好友成员名称；用户提供的具体成员与名称对照一致。其他构建不启用这段补充逻辑。生产 helper 仍固定于下方原提交，DLL、构建指纹检查和生命周期组件未更改；本次没有引入新上游其他功能。

本项目通过标准包依赖调用下列组件；v0.2.0 另在独立目录保留 helper 固定提交，说明见下文。版本来自本机项目虚拟环境；许可标识来自已安装发行包的元数据和附带许可文件。完整依赖约束见 `requirements-lock.txt`。

| 组件 | 实测版本 | 包声明许可 | 用途与来源 |
| --- | --- | --- | --- |
| Pillow | 13.0.0 | MIT-CMU | 棋盘 PNG 绘制、所选消息区域截图及 OCR 标签裁剪；https://github.com/python-pillow/Pillow |
| tzdata | 2026.5 | Apache-2.0 | Windows 上的 IANA 时区数据；https://github.com/python/tzdata |
| pywinauto | 0.6.9 | BSD 3-clause | 可选只读 UIA 探测及可见区域文本读取；https://github.com/pywinauto/pywinauto |
| pywin32 | 312 | PSF，附带组件许可见发行包 | pywinauto 所需 Windows API；https://github.com/mhammond/pywin32 |
| comtypes | 1.4.17 | MIT | UIA COM 支持；https://github.com/enthought/comtypes |
| six | 1.17.0 | MIT | pywinauto 的兼容依赖；https://github.com/benjaminp/six |
| pytest | 9.1.1 | MIT | 三个核心场景及两个最小接收回归；https://github.com/pytest-dev/pytest |

pytest 的解析、终端输出等传递依赖由包管理器安装，约束文件记录其版本；各自完整许可保留在 `.venv/Lib/site-packages/*dist-info/`。Python 3.12.12 运行时通过 uv 获取 python-build-standalone 发行，保留在 `.python/`，含运行时许可文件；它与 `.venv` 均不提交到 Git。

`characters.json` 和 v0.2.6 及之前的 `words.json` 为本项目显式维护的单字/常用词集合；v0.2.7 的第三方词条增补见上文。棋盘读取 Windows 已安装的 Arial Bold 或 Segoe UI Bold；本仓库不复制、分发字体。找不到系统字体时使用 Pillow 随包默认字体，其许可随 Pillow 发行包保留。

2026-10-30：`words.json` 扩展为 3～10 字母、2348 个项目维护的答案，保留原五字母词库。`ZhBot.exe` 从仓库的 `launcher/Launcher.cs` 使用 Windows 自带 .NET Framework v4 C# 编译器构建，调用已安装的 WinForms；未将 .NET、Python 或 helper DLL 嵌入 EXE。新增 PNG 转换代码使用已有 Pillow，未添加运行依赖或修改固定上游源码。

## Windows 系统 OCR（2026-10-29）

`src/wechat_reader/ocr.py` 与 `windows_ocr.ps1` 为本项目编写的调用封装，通过 Windows PowerShell 5.1 调用已安装的 `Windows.Media.Ocr.OcrEngine`。仓库不附带 Windows OCR 引擎或识别模型，也未复制第三方 OCR 项目的代码；图像处理复用已有 Pillow，未增加 Python 运行依赖。

本机已观察到 `en-US`、`zh-Hans-CN`、`de-DE` 识别语言，当前群聊标签调用 `en-US`。生产 OCR 的图像在内存中编码并通过本机进程传递，不上传或写入截图文件；本轮另行保留的临时探测图为 `runtime/group-visible-probe.png`，含聊天内容且不进入 Git。识别输出保留原始标签和 `windows-ocr` 来源。OCR 输出仅用于用户接受的本轮两位成员受限区分，特殊符号误识别、同名、改名与界面可见性限制见 README。

## v0.1.0 微信路线调查（当时未引入代码）

- [pywinauto 连接文档](https://pywinauto.readthedocs.io/en/latest/HowTo.html)支持按进程/窗口连接；本项目仅使用查询接口。
- [Microsoft UIA provider 说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-providersoverview)说明控件通过 provider 暴露辅助功能信息。窗口可枚举不等于消息正文可读。
- 核查 [easyChat 的 4.1.15.8 接收源码](https://github.com/LTEnjoy/easyChat/blob/main/versions/wechat_4_1_15_8.py)：`check_new_msg`、`get_dialogs` 等函数抛出 `NotImplementedError`；相关定位流程调用热键、点击和剪贴板操作。本项目未采用其代码或依赖，也未将 README 的版本声明作为真机接收证据。
- [wxauto 安装说明](https://docs.wxauto.org/docs/install.html)的免费版兼容声明到 4.1.8.107；[wxauto4](https://github.com/cluic/wxauto4)显示停止更新。本项目未安装这些组件，未要求微信降级。

上游来源与许可核查日期：2026-10-25。2026-10-29 本机微信 4.1.15.13 已按 README 记录的条件完成本轮受限验收，包括群内两位成员同正文的可见快照保留、受限 OCR 标签，以及滚动、遮挡、重启检查；群聊最终检查的新增内容通过 `snapshot` 读出，未记为 `new`。本轮延用上述 Python 依赖，增加 Windows 系统 OCR 调用，未复制第三方接收代码；最终 wheel 已确认包含本项目 OCR 封装、脚本和最新校验代码。

## v0.2.0 helper 原生桥接

来源：[Prometheus-first/helper](https://github.com/Prometheus-first/helper)，固定提交 `3e65e4bdaff438dc616f32d412175842fa138763`。源码、两个桥接 DLL、`LICENSE`、`THIRD_PARTY_NOTICES.md`、MinHook 1.3.4 源码和原许可保留于 `external/helper/`；获取脚本与摘要见 `external/helper.lock.json`、`scripts/fetch_helper.ps1`。

helper 原创部分使用 `LicenseRef-helper-noncommercial-1.0`：个人学习、研究、测试、娱乐和非商业自用；不授予商业使用权，免费分享须保留协议与声明。本项目没有把它重新标成 MIT 或 Apache。完整条款以随源码保留的 LICENSE 为准。两个 DLL 取自固定提交；上游声明由其原生源码和 MinHook 构建，本轮没有独立复现构建。

适配器直接调用后端与单条表情资源工具，不启动上游默认插件。必要的 run_selftest、桥接守护及原生生命周期文件完整保留。源码接口检查与真实兼容结果分别见 `docs/NATIVE_API.md`、`docs/COMPATIBILITY.md`。

新增已安装依赖（许可取自本机发行包元数据）：

| 包 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| pefile | 2023.2.7 | MIT | 原生 PE / 版本核验 |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause | 上游表情模块导入与格式处理 |
| cffi | 2.1.1 | MIT-0 | cryptography 依赖 |
| pycparser | 3.12 | BSD-3-Clause | cffi 依赖 |

现有 Pillow 13.0.0 保留；没有按上游全功能 requirements 降级现有环境，也没有安装本轮不使用的语音、模型或 FFmpeg 依赖。完整依赖许可文件保留在各自 dist-info 目录。
