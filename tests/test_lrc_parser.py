# -*- coding: utf-8 -*-
"""lrc_parser 的单元测试 —— 只用标准库，不需要 pytest。

在项目根目录运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lrc_parser import (  # noqa: E402
    decode_bytes,
    format_time,
    load_file,
    parse_lrc,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDecodeBytes(unittest.TestCase):
    def test_plain_ascii(self):
        text, enc = decode_bytes(b"hello [00:01.00] world")
        self.assertEqual(text, "hello [00:01.00] world")
        self.assertEqual(enc, "utf-8")

    def test_utf8_chinese(self):
        raw = "中文歌词测试".encode("utf-8")
        text, enc = decode_bytes(raw)
        self.assertEqual(text, "中文歌词测试")
        self.assertTrue(enc.startswith("utf-8"))

    def test_utf8_bom_is_stripped(self):
        raw = b"\xef\xbb\xbf" + "[ti:歌名]".encode("utf-8")
        text, enc = decode_bytes(raw)
        self.assertEqual(text, "[ti:歌名]")
        self.assertNotIn("\ufeff", text)
        self.assertEqual(enc, "utf-8-sig")

    def test_gb18030_fallback(self):
        raw = "[ti:测试]中文歌词".encode("gb18030")
        text, enc = decode_bytes(raw)
        self.assertEqual(text, "[ti:测试]中文歌词")
        self.assertEqual(enc, "gb18030")

    def test_empty_input(self):
        self.assertEqual(decode_bytes(b""), ("", "utf-8"))

    def test_never_raises_on_binary_garbage(self):
        text, enc = decode_bytes(bytes(range(256)) * 3)
        self.assertIsInstance(text, str)
        self.assertTrue(enc)


class TestFormatTime(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(format_time(0), "00:00.00")

    def test_fractional(self):
        self.assertEqual(format_time(4.5), "00:04.50")

    def test_over_one_minute(self):
        self.assertEqual(format_time(65.25), "01:05.25")

    def test_hour_long_track(self):
        self.assertEqual(format_time(3725.0), "62:05.00")

    def test_negative_is_clamped(self):
        self.assertEqual(format_time(-3), "00:00.00")

    def test_none(self):
        self.assertEqual(format_time(None), "")


class TestParseLrc(unittest.TestCase):
    def test_single_line(self):
        lyrics = parse_lrc("[00:12.34]第一行")
        self.assertTrue(lyrics.has_timestamps)
        self.assertEqual(len(lyrics.lines), 1)
        self.assertAlmostEqual(lyrics.lines[0].time, 12.34, places=4)
        self.assertEqual(lyrics.lines[0].text, "第一行")

    def test_millisecond_precision_variants(self):
        lyrics = parse_lrc(
            "[00:01]整秒\n[00:02.5]一位小数\n[00:03.25]两位小数\n[00:04.125]三位小数"
        )
        times = [line.time for line in lyrics.lines]
        self.assertAlmostEqual(times[0], 1.0, places=4)
        self.assertAlmostEqual(times[1], 2.5, places=4)
        self.assertAlmostEqual(times[2], 3.25, places=4)
        self.assertAlmostEqual(times[3], 4.125, places=4)

    def test_colon_as_decimal_separator(self):
        # 部分国产播放器写 [mm:ss:xx]
        lyrics = parse_lrc("[01:05:50]用冒号分隔毫秒")
        self.assertAlmostEqual(lyrics.lines[0].time, 65.5, places=4)

    def test_multiple_tags_on_one_line(self):
        # 合唱段的标准写法：一行挂多个时间
        lyrics = parse_lrc("[00:10.00][01:20.00]重复的副歌")
        self.assertEqual(len(lyrics.lines), 2)
        self.assertEqual([line.text for line in lyrics.lines], ["重复的副歌"] * 2)
        self.assertAlmostEqual(lyrics.lines[0].time, 10.0, places=4)
        self.assertAlmostEqual(lyrics.lines[1].time, 80.0, places=4)

    def test_lines_are_sorted(self):
        lyrics = parse_lrc("[00:30.00]后\n[00:10.00]先\n[00:20.00]中")
        self.assertEqual([line.text for line in lyrics.lines], ["先", "中", "后"])

    def test_metadata_is_parsed(self):
        lyrics = parse_lrc("[ti:夜曲]\n[ar:周杰伦]\n[al:十一月的萧邦]\n[by:某人]\n[00:01.00]词")
        self.assertEqual(lyrics.title, "夜曲")
        self.assertEqual(lyrics.artist, "周杰伦")
        self.assertEqual(lyrics.album, "十一月的萧邦")
        self.assertEqual(lyrics.metadata["by"], "某人")

    def test_offset_is_recorded_but_not_applied(self):
        lyrics = parse_lrc("[offset:+500]\n[00:10.00]不该被平移")
        self.assertEqual(lyrics.metadata["offset"], "+500")
        self.assertAlmostEqual(lyrics.lines[0].time, 10.0, places=4)

    def test_word_level_tags_are_stripped(self):
        lyrics = parse_lrc("[00:01.00]<00:01.00>逐字 <00:02.00>标签")
        self.assertEqual(lyrics.lines[0].text, "逐字 标签")
        self.assertNotIn("<", lyrics.lines[0].text)

    def test_bracketed_text_is_not_eaten(self):
        lyrics = parse_lrc("[00:09.00]第三行：[这不是时间标签] 是正文")
        self.assertEqual(lyrics.lines[0].text, "第三行：[这不是时间标签] 是正文")

    def test_empty_timed_lines_are_dropped(self):
        lyrics = parse_lrc("[00:10.00]有字\n[00:20.00]\n[00:30.00]也有字")
        self.assertEqual(len(lyrics.lines), 2)

    def test_all_empty_timed_lines_are_kept(self):
        # 如果整个文件的带时间行都没文字，那就原样保留，避免显示成全白
        lyrics = parse_lrc("[00:10.00]\n[00:20.00]")
        self.assertEqual(len(lyrics.lines), 2)
        self.assertTrue(lyrics.has_timestamps)

    def test_plain_text_without_timestamps(self):
        lyrics = parse_lrc("第一句\n第二句\n第三句")
        self.assertFalse(lyrics.has_timestamps)
        self.assertEqual([line.text for line in lyrics.lines], ["第一句", "第二句", "第三句"])
        self.assertTrue(all(line.time is None for line in lyrics.lines))
        self.assertEqual(lyrics.lines[0].time_label, "")

    def test_blank_lines_are_ignored(self):
        lyrics = parse_lrc("\n\n[00:01.00]只有一行\n\n")
        self.assertEqual(len(lyrics.lines), 1)

    def test_crlf_line_endings(self):
        lyrics = parse_lrc("[00:01.00]甲\r\n[00:02.00]乙\r\n")
        self.assertEqual([line.text for line in lyrics.lines], ["甲", "乙"])

    def test_empty_input_produces_nothing(self):
        lyrics = parse_lrc("")
        self.assertEqual(lyrics.lines, [])
        self.assertFalse(lyrics.has_timestamps)

    def test_plain_text_export_roundtrip(self):
        lyrics = parse_lrc("[00:01.00]甲\n[00:02.50]乙")
        self.assertEqual(lyrics.plain_text(), "[00:01.00] 甲\n[00:02.50] 乙")

    def test_unknown_bracket_key_falls_back_to_lyric_text(self):
        # [Note:hello] 不是已知元数据键，应该当歌词文本处理
        lyrics = parse_lrc("[00:01.00]正文\n[Note:hello]")
        self.assertNotIn("note", lyrics.metadata)
        self.assertEqual(lyrics.lines[0].text, "正文")


class TestSampleFile(unittest.TestCase):
    def test_bundled_demo(self):
        path = os.path.join(PROJECT_ROOT, "samples", "demo.lrc")
        self.assertTrue(os.path.exists(path), "samples/demo.lrc 应该随项目一起存在")

        lyrics = load_file(path)
        self.assertTrue(lyrics.has_timestamps)
        self.assertEqual(lyrics.title, "LRC 歌词查看器 · 示例歌词")
        self.assertEqual(lyrics.artist, "Demo Artist")

        # 示例文件里有 8 行带文字的歌词，1 行纯时间戳空行（应被过滤）
        self.assertEqual(len(lyrics.lines), 8)
        self.assertEqual(lyrics.lines[0].time, 0.0)
        times = [line.time for line in lyrics.lines]
        self.assertEqual(times, sorted(times), "解析结果必须按时间升序")

        joined = "\n".join(line.text for line in lyrics.lines)
        self.assertNotIn("<", joined, "逐字标签应该被去掉")
        self.assertIn("文件关联生效了", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
