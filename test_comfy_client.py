import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import comfy_client


class FakeComfy:
    """Answers /prompt, /history and /interrupt like ComfyUI, saving one render."""

    def __init__(self, comfy_dir, status="success", history=True):
        self.comfy_dir, self.status, self.history, self.calls = comfy_dir, status, history, []

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data) if data else None))
        if url.endswith("/prompt"):
            return {"prompt_id": "p1"}
        if url.endswith("/interrupt"):
            return {}
        if "/history/" in url:
            if not self.history:
                return {}
            prefix = self.calls[0][1]["prompt"]["15"]["inputs"]["filename_prefix"]
            folder, stem = prefix.split("/")
            out = self.comfy_dir / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            name = f"{stem}_00001_.png"
            Image.new("RGB", (32, 32)).save(out / name)
            return {"p1": {"status": {"status_str": self.status, "messages": ["boom"]},
                           "outputs": {"15": {"images": [{"filename": name, "subfolder": folder,
                                                          "type": "output"}]}}}}
        raise AssertionError(f"unexpected request {url}")


class TemplateTests(unittest.TestCase):
    def test_each_record_matches_its_template(self):
        for name, wf in comfy_client.WORKFLOWS.items():
            with self.subTest(name):
                prompt = comfy_client.load_template(wf)
                classes = {node["class_type"] for node in prompt.values()}
                self.assertEqual(prompt[wf.guide[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.composite[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.mask[0]]["class_type"], "LoadImageMask")
                self.assertEqual(prompt[wf.mask[0]]["inputs"]["channel"], "red")
                for node, key in (wf.guide, wf.composite, wf.mask, wf.positive, wf.negative,
                                  wf.seed, *wf.reference_inputs):
                    self.assertIn(key, prompt[node]["inputs"])
                for _folder, node, key in wf.model_files:
                    self.assertIn(key, prompt[node]["inputs"])
                for cls in wf.node_classes:
                    self.assertIn(cls, classes)
                self.assertEqual(prompt[wf.save]["class_type"], "SaveImage")
                sampler = prompt[wf.seed[0]]
                self.assertEqual(sampler["class_type"], "KSampler")
                self.assertEqual(prompt[sampler["inputs"]["model"][0]]["class_type"],
                                 "DifferentialDiffusion")
                latent = prompt[sampler["inputs"]["latent_image"][0]]
                self.assertEqual(latent["class_type"], "SetLatentNoiseMask")
                self.assertEqual(latent["inputs"]["mask"], [wf.mask[0], 0])
                encode = prompt[latent["inputs"]["samples"][0]]
                self.assertEqual(encode["class_type"], "VAEEncode")
                self.assertEqual(encode["inputs"]["pixels"], [wf.composite[0], 0])
                for node_id, node in prompt.items():
                    for value in node["inputs"].values():
                        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                            self.assertIn(value[0], prompt, f"node {node_id} links to {value[0]}")

    def test_2511_controlnet_reads_canny_of_the_guide(self):
        wf = comfy_client.WORKFLOWS["qwen-edit-2511-canny"]
        prompt = comfy_client.load_template(wf)
        apply = next(n for n in prompt.values() if n["class_type"] == "ControlNetApplyAdvanced")
        canny = prompt[apply["inputs"]["image"][0]]
        self.assertEqual((canny["class_type"], canny["inputs"]["image"]), ("Canny", [wf.guide[0], 0]))

    def test_qwen21_reference_uses_the_autogrow_container_path(self):
        # AITD's live check: a flat "image_1" key arrives as an unexpected keyword
        # and kills the render; ComfyUI rebuilds the dict from "images.image_1".
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        inputs = comfy_client.load_template(wf)["9"]["inputs"]
        self.assertIn("images.image_1", inputs)
        self.assertNotIn("image_1", inputs)
        self.assertEqual(wf.reference_inputs, (("9", "images.image_1"),))

    def test_default_workflow_is_registered(self):
        self.assertIn(comfy_client.DEFAULT_WORKFLOW, comfy_client.WORKFLOWS)


class RenderWindowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.comfy_dir = Path(tmp.name) / "comfy"
        self.inputs = Path(tmp.name) / "in"
        self.inputs.mkdir()
        for part in ("guide", "composite", "mask"):
            Image.new("RGB", (32, 32)).save(self.inputs / f"{part}.png")

    def render(self, workflow, reference="guide", http=None, timeout=60):
        http = http or FakeComfy(self.comfy_dir)
        path = comfy_client.render_window(
            comfy_client.WORKFLOWS[workflow], guide=self.inputs / "guide.png",
            composite=self.inputs / "composite.png", mask=self.inputs / "mask.png",
            reference=reference, positive="paint it", negative="no photo", seed=43,
            name="room_001_window-1", url="http://c", comfy_dir=self.comfy_dir, http=http,
            timeout=timeout, sleep=lambda s: None)
        return path, http

    def test_fills_the_2511_graph(self):
        path, http = self.render("qwen-edit-2511-canny")
        self.assertEqual(path, self.comfy_dir / "output" / "atl" / "room_001_window-1_00001_.png")
        prompt = http.calls[0][1]["prompt"]
        for node, part in (("1", "guide"), ("2", "composite"), ("3", "mask")):
            staged = f"__atl_room_001_window-1_{part}.png"
            self.assertEqual(prompt[node]["inputs"]["image"], staged)
            self.assertTrue((self.comfy_dir / "input" / staged).is_file())
        self.assertEqual((prompt["9"]["inputs"]["prompt"], prompt["10"]["inputs"]["prompt"]),
                         ("paint it", "no photo"))
        self.assertEqual(prompt["13"]["inputs"]["seed"], 43)
        self.assertEqual((prompt["9"]["inputs"]["image1"], prompt["10"]["inputs"]["image1"]),
                         (["1", 0], ["1", 0]))
        self.assertEqual(prompt["15"]["inputs"]["filename_prefix"], "atl/room_001_window-1")

    def test_the_reference_can_be_the_composite(self):
        _, http = self.render("qwen-image-2.1-i2i", reference="composite")
        inputs = http.calls[0][1]["prompt"]["9"]["inputs"]
        self.assertEqual(inputs["images.image_1"], ["2", 0])
        self.assertEqual((inputs["prompt"], inputs["negative_prompt"]), ("paint it", "no photo"))

    def test_an_unknown_reference(self):
        with self.assertRaisesRegex(ValueError, "reference must be one of guide, composite"):
            self.render("qwen-image-2.1-i2i", reference="both")

    def test_a_failed_execution(self):
        with self.assertRaisesRegex(RuntimeError, "ComfyUI execution failed"):
            self.render("qwen-image-2.1-i2i", http=FakeComfy(self.comfy_dir, status="error"))

    def test_a_timeout_interrupts_the_prompt(self):
        http = FakeComfy(self.comfy_dir, history=False)
        with self.assertRaises(TimeoutError):
            self.render("qwen-image-2.1-i2i", http=http, timeout=0)
        self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))


class PreflightTests(unittest.TestCase):
    def test_missing_model_files(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        with tempfile.TemporaryDirectory() as tmp:
            missing = comfy_client.missing_model_files(wf, tmp)
            self.assertEqual(missing, ["models/diffusion_models/qwen_image_2.1_bf16.safetensors",
                                       "models/text_encoders/qwen3vl_8b_bf16.safetensors",
                                       "models/vae/qwen_image_2.1_vae_bf16.safetensors"])
            for rel in missing:
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(comfy_client.missing_model_files(wf, tmp), [])

    def test_missing_nodes(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        known = {"TextEncodeQwenImage21", "DifferentialDiffusion", "SetLatentNoiseMask"}

        def http(url, timeout=60):
            cls = url.rsplit("/", 1)[1]
            if cls == "SetLatentNoiseMask":
                raise RuntimeError("HTTP 500")
            return {cls: {}} if cls in known else {}
        self.assertEqual(comfy_client.missing_nodes(wf, "http://c", http),
                         ["LoadImageMask", "SetLatentNoiseMask"])

    def test_is_up_and_free(self):
        calls = []

        def http(url, data=None, timeout=60):
            calls.append((url, data))
            return {}
        self.assertTrue(comfy_client.is_up("http://c", http))
        comfy_client.free_models("http://c", http)
        self.assertEqual(calls[-1], ("http://c/free",
                                     b'{"unload_models": true, "free_memory": true}'))

        def down(url, timeout=60):
            raise OSError("refused")
        self.assertFalse(comfy_client.is_up("http://c", down))


class SweepTests(unittest.TestCase):
    def test_removes_only_the_rooms_own_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output" / "atl"
            out.mkdir(parents=True)
            for name in ("room_001_window-1_00001_.png", "room_001_seam_00003_.png",
                         "room_002_window-1_00001_.png", "room_001_window-1_00001_.png.txt"):
                (out / name).touch()
            self.assertEqual(comfy_client.sweep_outputs("room_001", tmp), 2)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["room_001_window-1_00001_.png.txt", "room_002_window-1_00001_.png"])

    def test_no_output_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(comfy_client.sweep_outputs("room_001", tmp), 0)


if __name__ == "__main__":
    unittest.main()
