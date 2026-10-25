# 第三方来源与许可

本项目通过标准包依赖调用以下组件，没有复制其他微信机器人、NoneBot 或游戏项目的源码。版本来自本机项目虚拟环境；许可标识来自已安装发行包的元数据和附带许可文件。完整依赖约束见 `requirements-lock.txt`。

| 组件 | 实测版本 | 包声明许可 | 用途与来源 |
| --- | --- | --- | --- |
| Pillow | 13.0.0 | MIT-CMU | PNG 绘制；https://github.com/python-pillow/Pillow |
| tzdata | 2026.5 | Apache-2.0 | Windows 上的 IANA 时区数据；https://github.com/python/tzdata |
| pywinauto | 0.6.9 | BSD 3-clause | 可选只读 UIA 探测；https://github.com/pywinauto/pywinauto |
| pywin32 | 312 | PSF，附带组件许可见发行包 | pywinauto 所需 Windows API；https://github.com/mhammond/pywin32 |
| comtypes | 1.4.17 | MIT | UIA COM 支持；https://github.com/enthought/comtypes |
| six | 1.17.0 | MIT | pywinauto 的兼容依赖；https://github.com/benjaminp/six |
| pytest | 9.1.1 | MIT | 三个开发验证场景；https://github.com/pytest-dev/pytest |

pytest 的解析、终端输出等传递依赖由包管理器安装，约束文件记录其版本；各自完整许可保留在 `.venv/Lib/site-packages/*dist-info/`。Python 3.12.12 运行时通过 uv 获取 python-build-standalone 发行，保留在 `.python/`，含运行时许可文件；它与 `.venv` 均不提交到 Git。

`characters.json` 和 `words.json` 为本项目显式维护的单字/常用词集合，没有复制第三方词库。棋盘读取 Windows 已安装的 Arial Bold 或 Segoe UI Bold；本仓库不复制、分发字体。找不到系统字体时使用 Pillow 随包默认字体，其许可随 Pillow 发行包保留。

## 微信路线调查（未引入代码）

- [pywinauto 连接文档](https://pywinauto.readthedocs.io/en/latest/HowTo.html)支持按进程/窗口连接；本项目仅使用查询接口。
- [Microsoft UIA provider 说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-providersoverview)说明控件通过 provider 暴露辅助功能信息。窗口可枚举不等于消息正文可读。
- 核查 [easyChat 的 4.1.15.8 接收源码](https://github.com/LTEnjoy/easyChat/blob/main/versions/wechat_4_1_15_8.py)：`check_new_msg`、`get_dialogs` 等函数抛出 `NotImplementedError`；相关定位流程调用热键、点击和剪贴板操作。本项目未采用其代码或依赖，也未将 README 的版本声明作为真机接收证据。
- [wxauto 安装说明](https://docs.wxauto.org/docs/install.html)的免费版兼容声明到 4.1.8.107；[wxauto4](https://github.com/cluic/wxauto4)显示停止更新。本项目未安装这些组件，未要求微信降级。

核查日期：2026-10-25。当前微信真实群聊/私聊接收仍未完成。
