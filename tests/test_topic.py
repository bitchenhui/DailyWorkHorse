import json
import unittest
from unittest import mock

from enrich.topic import parse_topic
from sources import topic as topic_source

_VALID_RAW = """{
  "topic": "年轻人为什么存不下钱",
  "titles": ["月薪过万还是月光的钱去哪了", "存不下钱的真相"],
  "hook": "聊一个我们自己每天都在经历的事。",
  "points": [
    {"heading": "钱是看不见就没了的", "body": "工资到账先租房再点外卖，剩下的都是没被花掉的，而不是决定要存的。"},
    {"heading": "小额订阅是隐形出血点", "body": "视频会员云盘健身App，单看都不贵，加起来一个月小几百，你不取消它就一直扣。"},
    {"heading": "先存后花才是唯一解", "body": "发薪日当天把10%划进另一个账户，剩下的随便花也不心虚，存钱靠的不是意志力。"}
  ],
  "closing": "你上一次成功存下钱是因为什么？",
  "tags": ["#存钱", "消费观", "理财", "年轻人"]
}"""


class ParseTopicTests(unittest.TestCase):
    def test_valid_raw_is_parsed_and_normalized(self) -> None:
        copy = parse_topic(_VALID_RAW)

        self.assertEqual("年轻人为什么存不下钱", copy.topic)
        self.assertEqual(["月薪过万还是月光的钱去哪了", "存不下钱的真相"], copy.titles)
        self.assertEqual(3, len(copy.points))
        self.assertEqual(["存钱", "消费观", "理财", "年轻人"], copy.tags)
        self.assertTrue(copy.closing)

    def test_code_fenced_output_is_accepted(self) -> None:
        raw = f"```json\n{_VALID_RAW}\n```"

        self.assertEqual(3, len(parse_topic(raw).points))

    def test_incomplete_content_is_rejected_so_it_can_be_retried(self) -> None:
        raw = '{"topic":"", "titles":[], "hook":"", "points":[], "closing":"", "tags":[]}'

        with self.assertRaises(RuntimeError):
            parse_topic(raw)

    def _raw_with_points(self, points: list[dict]) -> str:
        data = json.loads(_VALID_RAW)
        data["points"] = points
        return json.dumps(data, ensure_ascii=False)

    def test_points_below_minimum_are_rejected(self) -> None:
        raw = self._raw_with_points(
            [
                {
                    "heading": "钱是看不见就没了的",
                    "body": "工资到账先租房再点外卖，剩下的都是没被花掉的，而不是决定要存的。",
                },
                {
                    "heading": "先存后花才是唯一解",
                    "body": "发薪日当天把10%划进另一个账户，剩下的随便花也不心虚，存钱靠的不是意志力。",
                },
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "不足"):
            parse_topic(raw)

    def test_degenerate_points_are_dropped(self) -> None:
        raw = self._raw_with_points(
            [
                {"heading": "占位观点", "body": "略"},
                {
                    "heading": "小额订阅是隐形出血点",
                    "body": "视频会员云盘健身App，单看都不贵，加起来一个月小几百，你不取消它就一直扣。",
                },
                {
                    "heading": "先存后花才是唯一解",
                    "body": "发薪日当天把10%划进另一个账户，剩下的随便花也不心虚，存钱靠的不是意志力。",
                },
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "不足"):
            parse_topic(raw)

    def test_extra_points_are_capped(self) -> None:
        filler = {
            "heading": "又一条",
            "body": "一条足够长的正文，用来凑满观点数量上限的测试。",
        }
        data = json.loads(_VALID_RAW)
        data["points"] = [filler] * 4 + data["points"]

        self.assertEqual(5, len(parse_topic(json.dumps(data, ensure_ascii=False)).points))


class PersonaTests(unittest.TestCase):
    def test_missing_persona_is_a_config_error(self) -> None:
        with self.assertRaisesRegex(SystemExit, "persona"):
            topic_source.load_persona(topic_source.PROJECT_ROOT / "no-such-persona.md")

    def test_extract_section_reads_between_headings(self) -> None:
        text = "## 固定栏目名\n\n茶余饭后\n\n## 免责声明\n\n不构成投资建议。\n"

        self.assertEqual("茶余饭后", topic_source.extract_section(text, "固定栏目名"))
        self.assertEqual("不构成投资建议。", topic_source.extract_section(text, "免责声明"))
        self.assertEqual("", topic_source.extract_section(text, "不存在的小节"))

    def test_first_line_skips_instructions_and_blank_lines(self) -> None:
        text = "（示例，请替换）\n\n> 引用里的说明\n茶余饭后\n备用行"

        self.assertEqual("茶余饭后", topic_source.first_line(text))


class ResolveTopicTests(unittest.TestCase):
    def test_override_wins_and_is_marked_manual(self) -> None:
        with mock.patch.dict(
            "os.environ", {"TOPIC_OVERRIDE": " 今天的主题 "}, clear=True
        ):
            self.assertEqual(("今天的主题", "手动指定"), topic_source.resolve_topic())

    def test_without_override_falls_back_to_auto(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(("", "自动选题"), topic_source.resolve_topic())


class PreviousTopicTests(unittest.TestCase):
    def test_first_line_of_the_last_note_is_the_previous_topic(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            note = Path(tmp) / "xhs_topic"
            note.mkdir()
            (note / "note.txt").write_text("上一期主题\n正文\n", encoding="utf-8")

            with mock.patch.object(topic_source, "DIST_DIR", Path(tmp)):
                self.assertEqual("上一期主题", topic_source.previous_topic())

    def test_missing_site_means_no_previous_topic(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            with mock.patch.object(topic_source, "DIST_DIR", Path(tmp)):
                self.assertEqual("", topic_source.previous_topic())


if __name__ == "__main__":
    unittest.main()
