# -*- coding: utf-8 -*-
"""LRC 歌词查看器 —— 界面主程序。

这个 App 存在的唯一理由，就是让 Android 的"打开方式"列表里能出现一个
能接 .lrc 的东西。界面刻意做得很克制：最重要的功能是"被文件管理器选中"。

桌面端调试界面请用 `python run.py`（它会先检查 Python / Kivy 版本，
报错信息比裸的 ImportError 清楚得多）。逻辑和 Android 端完全一样，
只有"读文件"这一步从 ContentResolver 换成了 open()。

注意：桌面预览需要 Python 3.8 ~ 3.13，Kivy 2.3.1 没有 cp314 的 wheel。
"""

from __future__ import annotations

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform

from lrc_parser import Lyrics, decode_bytes, parse_lrc

IS_ANDROID = platform == "android"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# 配色（深色，长时间看歌词更舒服）
# --------------------------------------------------------------------------- #
BG_COLOR = (0.055, 0.063, 0.078, 1)
TEXT_COLOR = (0.905, 0.918, 0.941, 1)
TIME_COLOR = (0.400, 0.451, 0.529, 1)
MUTED_COLOR = (0.482, 0.518, 0.588, 1)
ACCENT_COLOR = (0.290, 0.639, 0.976, 1)
BAR_BG = (0.086, 0.098, 0.118, 1)

# --------------------------------------------------------------------------- #
# 中文字体
#
# Kivy 自带的 Roboto 一个汉字字形都没有，不换字体的话中文歌词会全变成方框。
# 优先用打进 APK 的思源黑体（CI 构建时会下载），没有就退回到系统字体。
# 这个调用必须在任何 Label 被创建之前完成，所以放在模块导入期。
# --------------------------------------------------------------------------- #
CJK_FONT_NAME = "LRCViewerCJK"

CJK_FONT_CANDIDATES = (
    os.path.join(BASE_DIR, "fonts", "NotoSansSC-Regular.otf"),  # 随 APK 打包
    "/system/fonts/NotoSansCJK-Regular.ttc",                    # AOSP / 多数国产 ROM
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/DroidSansFallback.ttf",                      # 老设备兜底
    "/system/fonts/DroidSansChinese.ttf",
    "C:/Windows/Fonts/msyh.ttc",                                # 桌面调试
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def register_cjk_font() -> str:
    """注册一个包含汉字的字体，返回字体名供 Label 使用。"""
    for path in CJK_FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            LabelBase.register(name=CJK_FONT_NAME, fn_regular=path)
            print("[font] 已注册中文字体: {}".format(path))
            return CJK_FONT_NAME
        except Exception as exc:  # pragma: no cover - 依赖设备环境
            print("[font] 加载失败 {}: {}".format(path, exc))
    print("[font] 未找到中文字体，中文可能显示为方框")
    return "Roboto"


FONT = register_cjk_font()

BASE_FONT_SIZE = 17.0
MIN_FONT_SIZE = 11.0
MAX_FONT_SIZE = 40.0


class LyricRow(BoxLayout):
    """一行歌词：左边时间戳（可能为空），右边正文，正文自动换行并撑高行高。"""

    def __init__(self, line, font_size: float, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(26),
            padding=(dp(8), dp(3), dp(8), dp(3)),
            spacing=dp(8),
            **kwargs
        )
        self._time = Label(
            text=line.time_label,
            font_name=FONT,
            font_size=max(MIN_FONT_SIZE - 3.0, font_size - 3.0),
            color=TIME_COLOR,
            size_hint=(None, 1),
            width=dp(56),
            halign="right",
            valign="top",
        )
        self._time.bind(size=lambda widget, size: setattr(widget, "text_size", size))

        self._text = Label(
            text=line.text or " ",
            font_name=FONT,
            font_size=font_size,
            color=TEXT_COLOR,
            size_hint_x=1,
            halign="left",
            valign="top",
        )
        # Kivy 的坑：halign 只有在 text_size 设置之后才生效；
        # text_size 的宽度又必须跟着控件宽度走，才能拿到正确的换行高度。
        self._text.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
        self._text.bind(texture_size=self._on_texture)

        self.add_widget(self._time)
        self.add_widget(self._text)

    def _on_texture(self, widget, texture_size):
        self.height = max(dp(24), texture_size[1] + dp(8))

    def apply_font_size(self, font_size: float) -> None:
        self._text.font_size = font_size
        self._time.font_size = max(MIN_FONT_SIZE - 3.0, font_size - 3.0)


class ViewerRoot(BoxLayout):
    """整个界面：顶部信息栏 + 歌词滚动区 + 底部工具条。"""

    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.app = app
        self.font_size = BASE_FONT_SIZE
        self._rows = []
        self._lines = []
        self._flash_event = None
        self._status_text = "等待选择文件…"

        # ---- 顶部：标题 + 状态 ----
        header = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(64),
            padding=(dp(12), dp(8), dp(12), dp(6)), spacing=dp(2),
        )
        self.title_label = Label(
            text="LRC 歌词查看器", font_name=FONT, font_size=17,
            color=TEXT_COLOR, halign="left", valign="middle",
            size_hint_y=None, height=dp(26),
        )
        self.title_label.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.info_label = Label(
            text=self._status_text, font_name=FONT, font_size=12,
            color=MUTED_COLOR, halign="left", valign="middle",
            size_hint_y=None, height=dp(20),
        )
        self.info_label.bind(size=lambda w, s: setattr(w, "text_size", s))
        header.add_widget(self.title_label)
        header.add_widget(self.info_label)
        self.add_widget(header)

        # ---- 中间：歌词 ----
        self.scroll = ScrollView(bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(
            orientation="vertical", size_hint_y=None,
            spacing=dp(1), padding=(0, dp(6), 0, dp(12)),
        )
        self.content.bind(minimum_height=self.content.setter("height"))
        self.scroll.add_widget(self.content)
        self.add_widget(self.scroll)

        # ---- 底部：工具条 ----
        bar = BoxLayout(
            size_hint_y=None, height=dp(54), spacing=dp(6),
            padding=(dp(8), dp(6), dp(8), dp(8)),
        )
        bar.add_widget(self._make_button("打开文件", self.app.open_file, flex=2))
        bar.add_widget(self._make_button("A-", lambda *_: self.adjust_font(-1)))
        bar.add_widget(self._make_button("A+", lambda *_: self.adjust_font(1)))
        bar.add_widget(self._make_button("复制", self.copy_all, flex=1.4))
        self.add_widget(bar)

    # ---------------------------------------------------------------- 工具方法
    @staticmethod
    def _make_button(text: str, callback, flex: float = 1.0) -> Button:
        button = Button(
            text=text, font_name=FONT, font_size=14,
            size_hint_x=None, width=dp(0), color=TEXT_COLOR,
            background_normal="", background_color=BAR_BG,
        )
        button.size_hint_x = flex
        button.bind(on_release=callback)
        return button

    def flash(self, message: str) -> None:
        """在状态栏短暂显示一条提示，然后恢复原来的信息。"""
        if self._flash_event is not None:
            self._flash_event.cancel()
        self.info_label.text = message
        self._flash_event = Clock.schedule_once(
            lambda *_: setattr(self.info_label, "text", self._status_text), 2.0
        )

    # ---------------------------------------------------------------- 内容渲染
    def show_message(self, message: str) -> None:
        self.content.clear_widgets()
        self._rows = []
        self._lines = []
        self.title_label.text = "LRC 歌词查看器"
        self._status_text = "等待选择文件…"
        self.info_label.text = self._status_text

        holder = BoxLayout(
            orientation="vertical", size_hint_y=None, padding=(dp(16), dp(24)),
        )
        holder.bind(minimum_height=holder.setter("height"))
        label = Label(
            text=message, font_name=FONT, font_size=14, color=MUTED_COLOR,
            halign="center", valign="middle", size_hint_y=None,
        )
        label.bind(width=lambda w, width: setattr(w, "text_size", (width, None)))
        label.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1] + dp(16)))
        holder.add_widget(label)
        self.content.add_widget(holder)

    def set_lyrics(self, lyrics: Lyrics, display_name: str, encoding: str) -> None:
        self.title_label.text = lyrics.title or display_name or "未命名"
        self._lines = list(lyrics.lines)

        parts = []
        if lyrics.artist:
            parts.append(lyrics.artist)
        if lyrics.album:
            parts.append(lyrics.album)
        parts.append("{} 行".format(len(lyrics.lines)))
        if encoding:
            parts.append("编码 {}".format(encoding))
        if not lyrics.has_timestamps:
            parts.append("纯文本")
        self._status_text = " · ".join(parts)
        self.info_label.text = self._status_text

        self.content.clear_widgets()
        self._rows = []
        self.font_size = BASE_FONT_SIZE

        if not lyrics.lines:
            self.show_message("这个文件里没有可显示的歌词内容")
            return

        for line in lyrics.lines:
            row = LyricRow(line, self.font_size)
            self._rows.append(row)
            self.content.add_widget(row)
        self.scroll.scroll_y = 1
        self.info_label.text = self._status_text

    # ---------------------------------------------------------------- 交互
    def adjust_font(self, delta: float) -> None:
        new_size = min(MAX_FONT_SIZE, max(MIN_FONT_SIZE, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size
        for row in self._rows:
            row.apply_font_size(new_size)
        self.flash("字号 {}".format(int(round(new_size))))

    def copy_all(self, *_args) -> None:
        if not self._lines:
            self.flash("还没有内容可以复制")
            return
        # 延迟导入：剪贴板 provider 在 Android 上要等 Activity 完全起来才可靠
        from kivy.core.clipboard import Clipboard
        Clipboard.copy("\n".join(item.text for item in self._lines))
        self.flash("已复制 {} 行歌词".format(len(self._lines)))


class LRCViewerApp(App):
    title = "LRC 歌词查看器"

    def build(self):
        Window.clearcolor = BG_COLOR
        self.viewer = ViewerRoot(self)
        return self.viewer

    # ------------------------------------------------------------ 生命周期
    def on_start(self):
        if IS_ANDROID:
            self._setup_android()
        else:
            Clock.schedule_once(lambda *_: self._load_demo(), 0.2)

    def on_pause(self):
        # 必须返回 True：弹系统文件选择器 / 切到别的 App 时本 App 会被暂停，
        # 返回 False 的话 Activity 会被销毁，选择结果就回不来了。
        return True

    def on_resume(self):
        return True

    # ------------------------------------------------------------ Android
    def _setup_android(self) -> None:
        import android_file

        if android_file.bind_new_intent(self._on_new_intent):
            print("[intent] 已监听 onNewIntent")
        else:
            print("[intent] onNewIntent 监听失败，热启动可能复用不了窗口")

        # 等界面画完再去读文件，避免解析大文件时白屏
        Clock.schedule_once(lambda *_: self._load_launch_file(), 0.4)

    def _on_new_intent(self, uri) -> None:
        """回调在 Java UI 线程，必须切回 Kivy 主线程再碰界面。"""
        if uri is None:
            return
        Clock.schedule_once(lambda *_: self.load_uri(uri), 0)

    def _load_launch_file(self) -> None:
        import android_file

        uri = android_file.launch_uri()
        if uri is None:
            self._load_demo()
            return
        self.load_uri(uri)

    def load_uri(self, uri) -> None:
        import android_file

        try:
            picked = android_file.read_uri(uri)
        except Exception as exc:
            self.viewer.show_message("读取失败：{}".format(exc))
            return
        if not picked.raw:
            self.viewer.show_message(
                "读到的内容是空的。\n\n文件：{}".format(picked.display_name)
            )
            return
        self._render(picked.display_name, picked.raw)

    # ------------------------------------------------------------ 打开文件
    def open_file(self, *_args) -> None:
        if IS_ANDROID:
            import android_file

            def _callback(uri):
                if uri is None:  # 用户取消了
                    return
                Clock.schedule_once(lambda *_: self.load_uri(uri), 0)

            if not android_file.pick_file(_callback):
                self.viewer.show_message("无法调起系统文件选择器")
        else:
            self._open_desktop_chooser()

    def _open_desktop_chooser(self) -> None:
        # 延迟导入：kivy.uix.filechooser 体积不小，而且在 Android 上根本用不到，
        # 放在模块顶层只会拖慢手机上的冷启动。
        from kivy.uix.filechooser import FileChooserListView

        chooser = FileChooserListView(
            path=os.path.expanduser("~"),
            filters=["*.lrc", "*.LRC", "*.txt", "*"],
        )
        box = BoxLayout(orientation="vertical")
        box.add_widget(chooser)

        buttons = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        cancel = Button(text="取消", font_name=FONT, font_size=14)
        confirm = Button(text="打开", font_name=FONT, font_size=14)
        buttons.add_widget(cancel)
        buttons.add_widget(confirm)
        box.add_widget(buttons)

        popup = Popup(
            title="选择一个 .lrc 文件", content=box,
            size_hint=(0.92, 0.92), title_font=FONT,
        )
        cancel.bind(on_release=popup.dismiss)

        def _confirm(*_args):
            if not chooser.selection:
                return
            popup.dismiss()
            path = chooser.selection[0]
            try:
                with open(path, "rb") as handle:
                    raw = handle.read()
            except Exception as exc:
                self.viewer.show_message("读取失败：{}".format(exc))
                return
            self._render(os.path.basename(path), raw)

        confirm.bind(on_release=_confirm)
        popup.open()

    # ------------------------------------------------------------ 解析渲染
    def _load_demo(self) -> None:
        demo = os.path.join(BASE_DIR, "samples", "demo.lrc")
        if os.path.exists(demo):
            try:
                with open(demo, "rb") as handle:
                    raw = handle.read()
            except Exception:
                raw = None
            if raw:
                self._render("demo.lrc（示例）", raw)
                return
        self.viewer.show_message(
            "还没有打开任何文件。\n\n点下面的「打开文件」，"
            "或者在文件管理器里点一个 .lrc 文件并选择本应用。"
        )

    def _render(self, display_name: str, raw: bytes) -> None:
        text, encoding = decode_bytes(raw)
        lyrics = parse_lrc(text, encoding=encoding)
        self.viewer.set_lyrics(lyrics, display_name, encoding)


if __name__ == "__main__":
    LRCViewerApp().run()
