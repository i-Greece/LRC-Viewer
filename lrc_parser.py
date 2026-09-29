# -*- coding: utf-8 -*-
"""LRC 歌词解析器 —— 纯 Python，零第三方依赖。

为什么单独抽一个文件：
    整个 App 里唯一有"真正逻辑"的就是解析部分。把它和 Kivy / pyjnius 解耦后，
    在电脑上直接 `python -m unittest discover tests` 就能验证正确性，
    不必等 30 分钟的 APK 构建。

支持：
    * [mm:ss] / [mm:ss.x] / [mm:ss.xx] / [mm:ss.xxx] 以及用冒号分隔毫秒的写法
    * 一行多个时间标签（合唱段）
    * 元数据标签 [ti:] [ar:] [al:] [by:] [offset:] 等
    * 增强型逐字标签 <mm:ss.xx>（查看器里直接丢弃，只保留整行）
    * 完全没有时间标签的纯文本歌词
    * 中文常见编码自动探测（UTF-8 / GB18030 / Big5 …）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# [mm:ss] [mm:ss.x] [mm:ss.xx] [mm:ss.xxx]，也兼容 [mm:ss:xx]（部分国产播放器）
_TIME_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# 增强型逐字标签 <mm:ss.xx>
_WORD_TAG_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
# 元数据标签，要求整行匹配，避免误伤 "[00:09.00]第三行：[内容]"
_META_TAG_RE = re.compile(r"^\[([A-Za-z]+)\s*:\s*(.*?)\]\s*$")

# 已知的 LRC 元数据键（小写）。不在这个表里的 [xxx:yyy] 会被当成普通歌词文本。
META_KEYS = {
    "ti": "标题",
    "ar": "歌手",
    "al": "专辑",
    "au": "词作者",
    "by": "制作",
    "offset": "时间偏移",
    "length": "时长",
    "re": "编辑器",
    "ve": "版本",
    "tool": "生成工具",
}

# 编码探测顺序。
# gb18030 是 GBK / GB2312 的超集，能解出绝大多数简体中文文件，
# 但它几乎不会抛异常，所以必须排在严格 UTF-8 之后，否则会抢走 UTF-8 文件。
ENCODING_CHAIN: Tuple[str, ...] = ("utf-8", "gb18030", "big5", "shift_jis", "cp1252")

_BOM_UTF8 = b"\xef\xbb\xbf"


@dataclass
class LyricLine:
    """一行歌词。time 为 None 表示这行没有时间标签（纯文本歌词）。"""

    time: Optional[float]
    text: str

    @property
    def is_timed(self) -> bool:
        return self.time is not None

    @property
    def time_label(self) -> str:
        return format_time(self.time) if self.time is not None else ""


@dataclass
class Lyrics:
    """解析结果。"""

    metadata: Dict[str, str] = field(default_factory=dict)
    lines: List[LyricLine] = field(default_factory=list)
    encoding: str = ""
    has_timestamps: bool = False
    raw_text: str = ""

    @property
    def title(self) -> str:
        return self.metadata.get("ti", "")

    @property
    def artist(self) -> str:
        return self.metadata.get("ar", "")

    @property
    def album(self) -> str:
        return self.metadata.get("al", "")

    def plain_text(self) -> str:
        """还原成可复制的纯文本（带时间戳的会补回 [mm:ss.xx]）。"""
        out = []
        for line in self.lines:
            if line.is_timed:
                out.append("[{}] {}".format(line.time_label, line.text))
            else:
                out.append(line.text)
        return "\n".join(out)


def decode_bytes(raw: bytes) -> Tuple[str, str]:
    """把原始字节解码成文本，返回 (文本, 实际使用的编码名)。

    先严格 UTF-8，失败再依次尝试中文常见编码；全失败则用 UTF-8 的容错模式兜底，
    保证任何文件都不会让 App 崩掉。
    """
    if not raw:
        return "", "utf-8"
    if raw.startswith(_BOM_UTF8):
        # 带 BOM 的文件用 utf-8-sig 解码，否则首行会多出一个不可见的 \ufeff
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    for enc in ENCODING_CHAIN:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def format_time(seconds: Optional[float]) -> str:
    """秒 -> mm:ss.xx"""
    if seconds is None:
        return ""
    total = max(0.0, float(seconds))
    minutes, secs = divmod(total, 60.0)
    return "{:02d}:{:05.2f}".format(int(minutes), secs)


def _match_to_seconds(match: "re.Match") -> Optional[float]:
    """把一个时间标签的匹配对象换算成秒。"""
    try:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
    except (TypeError, ValueError):
        return None
    frac = match.group(3) or "0"
    if len(frac) == 1:
        frac_value = int(frac) / 10.0
    elif len(frac) == 2:
        frac_value = int(frac) / 100.0
    else:
        frac_value = int(frac) / 1000.0
    return minutes * 60 + seconds + frac_value


def parse_lrc(text: str, encoding: str = "") -> Lyrics:
    """解析 LRC 文本。

    注意：[offset:xxx] 只记录在 metadata 里，不参与时间换算。
    各家播放器对 offset 的符号约定并不统一，擅自平移只会让时间戳变得更不可信，
    而查看器的职责是"如实显示文件内容"。
    """
    metadata: Dict[str, str] = {}
    timed: List[LyricLine] = []
    plain: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        meta = _META_TAG_RE.match(line)
        if meta and meta.group(1).lower() in META_KEYS:
            metadata[meta.group(1).lower()] = meta.group(2).strip()
            continue

        stamps = list(_TIME_TAG_RE.finditer(line))
        if stamps:
            # 去掉所有时间标签和逐字标签，剩下的就是歌词正文
            body = _TIME_TAG_RE.sub("", line)
            body = _WORD_TAG_RE.sub("", body).strip()
            for stamp in stamps:
                seconds = _match_to_seconds(stamp)
                if seconds is not None:
                    timed.append(LyricLine(time=seconds, text=body))
            continue

        cleaned = _WORD_TAG_RE.sub("", line).strip()
        if cleaned:
            plain.append(cleaned)

    if timed:
        timed.sort(key=lambda item: item.time)
        # LRC 里常见的 "[00:20.00]" 空行只是段落间隔，显示出来是一堆空行，过滤掉。
        # 但如果整个文件所有时间行都没文字，那就原样保留，避免显示成空白。
        non_empty = [item for item in timed if item.text]
        if non_empty:
            timed = non_empty
        return Lyrics(
            metadata=metadata,
            lines=timed,
            encoding=encoding,
            has_timestamps=True,
            raw_text=text,
        )

    if not plain:
        # 全是空行或只有元数据，退化成"逐行显示原文"
        plain = [line.strip() for line in text.splitlines() if line.strip()]

    return Lyrics(
        metadata=metadata,
        lines=[LyricLine(time=None, text=item) for item in plain],
        encoding=encoding,
        has_timestamps=False,
        raw_text=text,
    )


def load_file(path: str) -> Lyrics:
    """从磁盘读取并解析（桌面端 / 测试用；Android 上走 android_file.read_uri）。"""
    with open(path, "rb") as handle:
        raw = handle.read()
    text, encoding = decode_bytes(raw)
    return parse_lrc(text, encoding=encoding)
