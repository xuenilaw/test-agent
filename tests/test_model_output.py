import unittest

from test_agent.model_output import unwrap_json_fence


class UnwrapJsonFenceTests(unittest.TestCase):
    def test_plain_json_is_unchanged(self):
        self.assertEqual(unwrap_json_fence('{"a": 1}'), '{"a": 1}')

    def test_json_and_bare_fences_are_removed(self):
        for fence in ("```json", "```JSON", "```"):
            self.assertEqual(unwrap_json_fence(f'{fence}\n{{"a": 1}}\n```\n'), '{"a": 1}')

    def test_text_outside_the_fence_is_not_removed(self):
        for text in ('Plan:\n```json\n{"a": 1}\n```', '```json\n{"a": 1}\n```\nDone.',
                     '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'):
            self.assertEqual(unwrap_json_fence(text), text)
