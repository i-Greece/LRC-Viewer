# -*- coding: utf-8 -*-
"""本地预览入口，等价于 `python main.py`，只是多一层依赖检查。

    python run.py

Android 打包不会用到这个文件（buildozer.spec 的入口是 main.py）。
"""

from __future__ import annotations

import sys

# Kivy 2.3.1 的 Windows wheel 只覆盖 cp38~cp313。
# 在 3.14 上 pip 会转为源码编译，而编译依赖的 kivy_deps.sdl2_dev~=0.8.0
# 同样没有 cp314 wheel，报错信息又完全看不出真正的原因，所以这里先拦一道。
MAX_PYTHON = (3, 13)
MIN_PYTHON = (3, 8)


def _check_python() -> bool:
    if sys.version_info[:2] > MAX_PYTHON:
        print(
            "当前 Python 是 {}.{}，Kivy 目前还不支持。\n"
            "\n"
            "Kivy 2.3.1 的 Windows 预编译包只到 cp313，在更高的版本上 pip 会去\n"
            "下载源码编译，而它的编译依赖 kivy_deps.sdl2_dev~=0.8.0 也没有对应\n"
            "的 wheel，于是你会看到：\n"
            "\n"
            "    ERROR: Could not find a version that satisfies the requirement\n"
            "           kivy_deps.sdl2_dev~=0.8.0 (from versions: none)\n"
            "\n"
            "解决办法：用 Python 3.12 或 3.13 建虚拟环境，例如\n"
            "\n"
            '    py -3.13 -m venv .venv          # Windows（用 py 启动器选版本）\n'
            "    .venv\\Scripts\\pip install -r requirements.txt\n"
            "    .venv\\Scripts\\python run.py\n"
            "\n"
            "注意：这个限制只影响桌面预览。云端构建 APK 走的是 Linux 上的\n"
            "Python 3.11，不受影响。".format(*sys.version_info[:2])
        )
        return False

    if sys.version_info[:2] < MIN_PYTHON:
        print("Kivy 需要 Python 3.8 及以上，当前是 {}.{}。".format(*sys.version_info[:2]))
        return False

    return True


def main() -> int:
    if not _check_python():
        return 1

    try:
        import kivy  # noqa: F401
    except ImportError:
        print("还没有安装 Kivy，先执行：\n\n    pip install -r requirements.txt\n")
        return 1

    from main import LRCViewerApp

    print("正在启动 LRC 歌词查看器（桌面预览模式）…")
    LRCViewerApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
