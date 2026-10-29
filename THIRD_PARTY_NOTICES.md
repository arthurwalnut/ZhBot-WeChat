# 第三方来源与许可

本项目通过标准包依赖调用以下组件，没有复制其他微信机器人、NoneBot 或游戏项目的源码。版本来自本机项目虚拟环境；许可标识来自已安装发行包的元数据和附带许可文件。完整依赖约束见 `requirements-lock.txt`。

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

`characters.json` 和 `words.json` 为本项目显式维护的单字/常用词集合，没有复制第三方词库。棋盘读取 Windows 已安装的 Arial Bold 或 Segoe UI Bold；本仓库不复制、分发字体。找不到系统字体时使用 Pillow 随包默认字体，其许可随 Pillow 发行包保留。

## Windows 系统 OCR（2026-10-29）

`src/wechat_reader/ocr.py` 与 `windows_ocr.ps1` 为本项目编写的调用封装，通过 Windows PowerShell 5.1 调用已安装的 `Windows.Media.Ocr.OcrEngine`。仓库不附带 Windows OCR 引擎或识别模型，也未复制第三方 OCR 项目的代码；图像处理复用已有 Pillow，未增加 Python 运行依赖。

本机已观察到 `en-US`、`zh-Hans-CN`、`de-DE` 识别语言，当前群聊标签调用 `en-US`。生产 OCR 的图像在内存中编码并通过本机进程传递，不上传或写入截图文件；本轮另行保留的临时探测图为 `runtime/group-visible-probe.png`，含聊天内容且不进入 Git。识别输出保留原始标签和 `windows-ocr` 来源。OCR 输出仅用于用户接受的本轮两位成员受限区分，特殊符号误识别、同名、改名与界面可见性限制见 README。

## 微信路线调查（未引入代码）

- [pywinauto 连接文档](https://pywinauto.readthedocs.io/en/latest/HowTo.html)支持按进程/窗口连接；本项目仅使用查询接口。
- [Microsoft UIA provider 说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-providersoverview)说明控件通过 provider 暴露辅助功能信息。窗口可枚举不等于消息正文可读。
- 核查 [easyChat 的 4.1.15.8 接收源码](https://github.com/LTEnjoy/easyChat/blob/main/versions/wechat_4_1_15_8.py)：`check_new_msg`、`get_dialogs` 等函数抛出 `NotImplementedError`；相关定位流程调用热键、点击和剪贴板操作。本项目未采用其代码或依赖，也未将 README 的版本声明作为真机接收证据。
- [wxauto 安装说明](https://docs.wxauto.org/docs/install.html)的免费版兼容声明到 4.1.8.107；[wxauto4](https://github.com/cluic/wxauto4)显示停止更新。本项目未安装这些组件，未要求微信降级。

上游来源与许可核查日期：2026-10-25。2026-10-29 本机微信 4.1.15.13 已按 README 记录的条件完成本轮受限验收，包括群内两位成员同正文的可见快照保留、受限 OCR 标签，以及滚动、遮挡、重启检查；群聊最终检查的新增内容通过 `snapshot` 读出，未记为 `new`。本轮延用上述 Python 依赖，增加 Windows 系统 OCR 调用，未复制第三方接收代码；最终 wheel 已确认包含本项目 OCR 封装、脚本和最新校验代码。
