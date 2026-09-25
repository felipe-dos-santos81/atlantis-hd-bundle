import base64
import io
import json
import unittest

from PIL import Image

import prompts as p

CAPTION = ("SCENE: a newspaper page.\nVIEW: flat, frontal.\n"
           "**TEXT:** German Wizard Splits Atom (headline, top)\n"
           "**INVARIANTS:** the photograph sits below the headline.")


class FakeVLM:
    """Answers /chat/completions with `content`, recording each request."""

    def __init__(self, content, finish="stop"):
        self.content, self.finish, self.calls = content, finish, []

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data), timeout, token))
        return {"choices": [{"finish_reason": self.finish,
                             "message": {"content": self.content}}]}


def decoded_size(part):
    data = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as im:
        return im.size


class TextSectionTests(unittest.TestCase):
    def test_text_section(self):
        cases = {
            "extracts until the next label": (CAPTION, "German Wizard Splits Atom (headline, top)"),
            "none - stated": ("SCENE: a cave.\nTEXT: none.\nINVARIANTS: x", None),
            "none - absent": ("SCENE: a cave.", None),
            "multi line": ("TEXT: ARTIFACTS (sign)\nAPOTHECARY (door)\nPALETTE: ochre",
                          "ARTIFACTS (sign)\nAPOTHECARY (door)"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(p.text_section(text), expected)


class RenderPromptTests(unittest.TestCase):
    def test_scene(self):
        text = p.render_prompt("SCENE: a study.", "scene", reference="<image1>")
        self.assertTrue(text.startswith("Repaint <image1> as a high-definition hand-painted"))
        self.assertIn("REFERENCE OBSERVATIONS:\nSCENE: a study.", text)
        self.assertNotIn("LETTERING", text)
        self.assertNotIn("CORRECT THESE", text)

    def test_insert_carries_its_lettering(self):
        self.assertIn("LETTERING:\nGerman Wizard Splits Atom (headline, top)",
                      p.render_prompt(CAPTION, "insert"))

    def test_insert_without_a_text_section(self):
        # Review Focus: a hand-edited insert caption with no TEXT section.
        text = p.render_prompt("SCENE: a stone tablet.", "insert")
        self.assertIn(p.INSERT_RULES, text)
        self.assertNotIn("LETTERING:", text)

    def test_window_note_and_corrections(self):
        note = p.window_note(248, 568, 0, 568)
        self.assertIn("from 44% to 100%", note)
        text = p.render_prompt("SCENE: a street.", "scene", ["the awning moved left"], note)
        self.assertIn(note, text)
        self.assertIn("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                      "REFERENCE LAYOUT:\nthe awning moved left", text)


class RequestTests(unittest.TestCase):
    def test_caption_room(self):
        with self.subTest("sends every image"):
            vlm = FakeVLM("SCENE: x")
            images = [Image.new("RGB", (640, 144)), Image.new("RGB", (1280, 576))]
            self.assertEqual(p.caption_room(images, vlm, "http://h/v1/", "m", "k"), "SCENE: x")
            url, payload, timeout, token = vlm.calls[0]
            self.assertEqual((url, timeout, token), ("http://h/v1/chat/completions",
                                                     p.CAPTION_TIMEOUT, "k"))
            parts = payload["messages"][1]["content"]
            self.assertEqual((parts[0]["text"], len(parts)), (p.CAPTION_QUESTION, 3))
            self.assertNotIn("response_format", payload)
        with self.subTest("a truncated answer is refused"):
            with self.assertRaisesRegex(ValueError, "truncated"):
                p.caption_room([Image.new("RGB", (8, 8))], FakeVLM("x", "length"), "http://h/v1",
                               "m", "")

    def test_images_are_scaled_to_the_longer_side(self):
        for size, expected in (((320, 144), (1280, 576)), ((2560, 400), (1280, 200))):
            with self.subTest(size=size):
                self.assertEqual(decoded_size(p._image(Image.new("RGB", size))), expected)

    def test_review_sends_pairs_then_the_overview(self):
        vlm = FakeVLM('{"accepted": false, "issues": ["window 2: the awning moved; move it back"]}')
        pairs = [(Image.new("RGB", (64, 32)), Image.new("RGB", (64, 32)))] * 2
        verdict = p.review_room(pairs, Image.new("RGB", (128, 32)), "insert", CAPTION, vlm,
                                "http://h/v1", "m", "")
        self.assertEqual(verdict, {"accepted": False,
                                   "issues": ["window 2: the awning moved; move it back"]})
        payload = vlm.calls[0][1]
        content = payload["messages"][1]["content"]
        self.assertIn("This room has 2 window(s). Kind: insert. Expected lettering: "
                      "German Wizard Splits Atom (headline, top).", content[0]["text"])
        self.assertEqual(len(content), 1 + 5)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_vlm_is_serving(self):
        self.assertTrue(p.vlm_is_serving("http://h/v1", "m",
                                         lambda url, **kw: {"data": [{"id": "m"}]}))
        self.assertFalse(p.vlm_is_serving("http://h/v1", "m",
                                          lambda url, **kw: {"data": [{"id": "other"}]}))

        def down(url, **kw):
            raise OSError("connection refused")
        self.assertFalse(p.vlm_is_serving("http://h/v1", "m", down))


class ParseReviewTests(unittest.TestCase):
    def test_plain_fenced_and_wrapped_json(self):
        for text in ('{"accepted": true, "issues": []}',
                     '```json\n{"accepted": true, "issues": []}\n```',
                     'Verdict: {"accepted": true, "issues": []} done'):
            with self.subTest(text=text):
                self.assertEqual(p.parse_review(text), {"accepted": True, "issues": []})

    def test_malformed_verdicts(self):
        for text, message in (('{"accepted": "yes", "issues": []}', "boolean accepted"),
                              ('{"accepted": false, "issues": [""]}', "nonempty issue strings"),
                              ('{"accepted": true, "issues": ["moved"]}', "contradicts")):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, message):
                    p.parse_review(text)


if __name__ == "__main__":
    unittest.main()
