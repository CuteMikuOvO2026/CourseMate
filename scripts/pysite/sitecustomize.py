# -*- coding: utf-8 -*-
"""只在本机安装依赖时使用的兼容补丁。

本机 Windows 沙箱环境下，``os.mkdir(path, 0o700)`` 创建出的目录会被一个
未知 SID 占用，当前用户随后无法写入，导致 pip / venv 的临时目录失败。
该补丁把 0o700 改成 0o777，仅在通过 PYTHONPATH 指向的安装命令中生效，
应用运行时不加载。
"""

import os

_original_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *, dir_fd=None):
    if mode == 0o700:
        mode = 0o777
    return _original_mkdir(path, mode, dir_fd=dir_fd)


os.mkdir = _mkdir
