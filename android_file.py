# -*- coding: utf-8 -*-
"""Android 侧的文件读取桥接层（pyjnius）。

这个模块回答一个很具体的问题：
    文件管理器点开 .lrc 时，Android 不会把"文件路径"给我们，而是给一个
    content:// 的 URI（Android 7 起禁止 App 之间传递 file:// URI）。
    所以绝对不能用 open() 去读，必须走 ContentResolver.openInputStream()。

读取策略有个小心机：
    用 ISO-8859-1 逐行读。ISO-8859-1 是"字节透明"的 —— 每个字节原样映射成
    U+0000..U+00FF，不会做任何解码，也就不会因为编码猜错而丢字符。
    再 encode('latin-1') 还原成原始字节，把"猜编码"这件事留给
    lrc_parser.decode_bytes() 用纯 Python 做（那边可以随意写单元测试）。

桌面端 import 本模块不会报错，IS_ANDROID 为 False，所有函数安全返回。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    from jnius import autoclass  # type: ignore
    _HAS_JNIUS = True
except Exception:  # pragma: no cover - 桌面端没有 pyjnius
    autoclass = None  # type: ignore
    _HAS_JNIUS = False

IS_ANDROID = _HAS_JNIUS and any(
    key in os.environ
    for key in ("ANDROID_ARGUMENT", "ANDROID_PRIVATE", "ANDROID_APP_PATH",
                "P4A_BOOTSTRAP")
)

# 自己发起 ACTION_OPEN_DOCUMENT 时用的请求码，随便取一个不冲突的值
PICK_REQUEST_CODE = 0x4C52  # 'LR'

_DISPLAY_NAME_COLUMN = "_display_name"  # OpenableColumns.DISPLAY_NAME

# pick_file 的状态：回调只挂一次监听器，等待中的回调放在这里
_pending_pick_callback: Optional[Callable[[Optional[Any]], None]] = None
_pick_listener_bound = False


@dataclass
class PickedFile:
    """从 URI 读出来的一个文件。"""

    display_name: str
    uri_string: str
    raw: bytes


def _activity() -> Any:
    """拿到当前 Activity（PythonActivity.mActivity）。"""
    python_activity = autoclass("org.kivy.android.PythonActivity")
    return python_activity.mActivity


def display_name_of(uri: Any) -> str:
    """尽量取到用户看得见的文件名。

    content:// 的 path 段通常是无意义的数字 ID（如 /document/1234），
    真正的文件名要通过 MediaStore/OpenableColumns 查询。
    部分第三方 ROM 的文件管理器的 ContentProvider 不实现 _display_name，
    这时退化成用 URI 最后一段。
    """
    try:
        resolver = _activity().getContentResolver()
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is not None:
            try:
                index = cursor.getColumnIndex(_DISPLAY_NAME_COLUMN)
                if index >= 0 and cursor.moveToFirst():
                    name = cursor.getString(index)
                    if name:
                        return str(name)
            finally:
                cursor.close()
    except Exception:
        pass

    try:
        segment = uri.getLastPathSegment()
        if segment:
            from urllib.parse import unquote
            return unquote(str(segment)).split("/")[-1]
    except Exception:
        pass

    return "lyrics.lrc"


def _stream_to_bytes(stream: Any) -> bytes:
    """把 java.io.InputStream 读成 Python bytes（字节透明，不猜编码）。"""
    buffered_reader = autoclass("java.io.BufferedReader")
    input_stream_reader = autoclass("java.io.InputStreamReader")

    reader = buffered_reader(input_stream_reader(stream, "ISO-8859-1"))
    try:
        chunks = []
        while True:
            line = reader.readLine()
            if line is None:
                break
            chunks.append(line)
    finally:
        try:
            reader.close()
        except Exception:
            pass

    return "\n".join(chunks).encode("latin-1")


def read_uri(uri: Any) -> PickedFile:
    """读取 URI 指向的全部内容。失败时抛异常，由调用方展示给用户。"""
    name = display_name_of(uri)
    try:
        uri_string = str(uri.toString())
    except Exception:
        uri_string = ""

    resolver = _activity().getContentResolver()
    stream = resolver.openInputStream(uri)
    if stream is None:
        raise IOError("系统拒绝了这次读取（openInputStream 返回 null）")

    try:
        raw = _stream_to_bytes(stream)
    finally:
        try:
            stream.close()
        except Exception:
            pass

    return PickedFile(display_name=name, uri_string=uri_string, raw=raw)


def uri_from_intent(intent: Any) -> Optional[Any]:
    """从 Intent 里挖出文件 URI。

    覆盖三种常见投递方式：
      1. ACTION_VIEW 的标准 data（绝大多数文件管理器）
      2. ACTION_SEND 的 EXTRA_STREAM（分享菜单）
      3. ClipData（部分管理器和"多选发送"用这个）
    """
    if intent is None:
        return None

    try:
        data = intent.getData()
        if data is not None:
            return data
    except Exception:
        pass

    try:
        intent_cls = autoclass("android.content.Intent")
        extra = intent.getParcelableExtra(intent_cls.EXTRA_STREAM)
        if extra is not None:
            return extra
    except Exception:
        pass

    try:
        clip = intent.getClipData()
        if clip is not None and clip.getItemCount() > 0:
            return clip.getItemAt(0).getUri()
    except Exception:
        pass

    return None


def launch_uri() -> Optional[Any]:
    """冷启动：App 是被"打开某个 .lrc"拉起来的，从 Activity 的 Intent 取 URI。"""
    if not IS_ANDROID:
        return None
    try:
        return uri_from_intent(_activity().getIntent())
    except Exception:
        return None


def bind_new_intent(callback: Callable[[Optional[Any]], None]) -> bool:
    """热启动：App 已经在运行时，再从文件管理器打开一个 lrc。

    配合 buildozer.spec 里的 android.manifest.launch_mode = singleTask，
    系统不会新建 Activity，而是回调 onNewIntent。
    回调发生在 Java UI 线程，调用方需要自己切回 Kivy 主线程（Clock.schedule_once）。
    """
    if not IS_ANDROID:
        return False
    try:
        from android import activity  # p4a 的 android recipe 提供
        activity.bind(on_new_intent=lambda intent: callback(uri_from_intent(intent)))
        return True
    except Exception:
        return False


def pick_file(callback: Callable[[Optional[Any]], None]) -> bool:
    """主动弹系统文件选择器（ACTION_OPEN_DOCUMENT）。

    用系统选择器而不是自己遍历目录，好处是不需要任何存储权限：
    用户选中的文件会临时授权给我们。

    监听器只在第一次调用时注册一次，回调存在模块级变量里 ——
    否则用户每点一次「打开文件」就会多挂一个监听器，回调被触发多次。
    """
    global _pending_pick_callback, _pick_listener_bound
    if not IS_ANDROID:
        return False
    try:
        from android import activity
        intent_cls = autoclass("android.content.Intent")
        activity_cls = autoclass("android.app.Activity")

        def _on_result(request_code, result_code, intent):
            global _pending_pick_callback
            if request_code != PICK_REQUEST_CODE:
                return
            cb, _pending_pick_callback = _pending_pick_callback, None
            if cb is None:
                return
            if result_code != activity_cls.RESULT_OK or intent is None:
                cb(None)
                return
            cb(uri_from_intent(intent))

        if not _pick_listener_bound:
            activity.bind(on_activity_result=_on_result)
            _pick_listener_bound = True

        _pending_pick_callback = callback

        intent = intent_cls(intent_cls.ACTION_OPEN_DOCUMENT)
        intent.addCategory(intent_cls.CATEGORY_OPENABLE)
        intent.setType("*/*")
        _activity().startActivityForResult(intent, PICK_REQUEST_CODE)
        return True
    except Exception:
        _pending_pick_callback = None
        return False
