"""Read-only prerequisites for the Windows desktop bot, not WeChat compatibility."""
import ctypes
import os
import struct
import sys


def check_windows_desktop():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise ValueError('需要 Windows x64 和 64 位 Python')
    import winreg
    version = sys.getwindowsversion()
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'SOFTWARE\Microsoft\Windows NT\CurrentVersion',
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        installation = winreg.QueryValueEx(key, 'InstallationType')[0]
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        framework = winreg.QueryValueEx(key, 'Release')[0]
    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise OSError('无法读取当前 Windows 会话')
    details = dict(major=version.major, build=version.build, installation=installation,
                   framework_release=framework, session_id=session.value)
    validate_desktop(details)
    return details


def validate_desktop(details):
    if details['major'] < 10:
        raise ValueError('需要 Windows 10/11 或 Windows Server 2016 及以后的桌面安装')
    if details['installation'] not in ('Client', 'Server'):
        raise ValueError('需要 Windows 桌面；服务器请选择 Desktop Experience，Server Core/Nano 不支持')
    if details['framework_release'] < 528040:
        raise ValueError('需要启用 .NET Framework 4.8 或更高的 4.x 版本')
    if details['session_id'] == 0:
        raise ValueError('请在机器人用户已登录的交互桌面运行，不支持 Session 0 服务')
