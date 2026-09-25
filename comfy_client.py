"""Thin client for the local ComfyUI HTTP API.

The only module that knows workflow node ids. WORKFLOWS records, per render
workflow, the template file and where the driver's values go:
  guide       LoadImage: the window of the 4x guide (the 2511 graph's Canny input)
  composite   LoadImage: the guide window with the held overlap from the stitch,
              VAE-encoded as the latent the sampler starts from
  mask        LoadImageMask (red channel): 255 paints, 0 keeps (SetLatentNoiseMask)
  reference_inputs  the encoder inputs that receive the reference image, which
              the driver points at the guide or the composite
  positive, negative, seed, save  as named
The HTTP plumbing (http_json, is_up, free_models, missing_model_files,
missing_nodes, wait_history, stage_input, execute, output_path) comes from the
AITD kit's comfy_client.py.
"""
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

HISTORY_TIMEOUT = 1800
POLL_SECONDS = 2
OUTPUT_PREFIX = "atl"
REPO_DIR = Path(__file__).resolve().parent

# name:        registry key, also written into attempt-N.prompt.txt and attempt-N.json
# template:    workflow file, relative to the repository (absolute paths work too)
# guide, composite, mask: (node id, input key) that receive the three staged images
# reference_inputs: (node id, input key) pairs linked to the reference image
# positive, negative, seed: (node id, input key)
# save:        SaveImage node id
# model_files: (models subfolder, node id, input key) ComfyUI must have on disk
# node_classes: class_type values the ComfyUI build must know
# reference:   how the positive prompt names the window
Workflow = namedtuple("Workflow", "name template guide composite mask reference_inputs "
                                  "positive negative seed save model_files node_classes "
                                  "reference")

MASK_CLASSES = ("LoadImageMask", "SetLatentNoiseMask", "DifferentialDiffusion")

WORKFLOWS = {
    "qwen-edit-2511-canny": Workflow(
        name="qwen-edit-2511-canny",
        template="recreation_qwen2511_canny.json",
        guide=("1", "image"), composite=("2", "image"), mask=("3", "image"),
        reference_inputs=(("9", "image1"), ("10", "image1")),
        positive=("9", "prompt"), negative=("10", "prompt"), seed=("13", "seed"), save="15",
        model_files=(("diffusion_models", "5", "unet_name"),
                     ("text_encoders", "4", "clip_name"),
                     ("vae", "6", "vae_name"),
                     ("controlnet", "31", "control_net_name")),
        node_classes=("TextEncodeQwenImageEditPlus", "ControlNetApplyAdvanced",
                      "SetUnionControlNetType", "Canny") + MASK_CLASSES,
        reference="the provided reference image"),
    "qwen-image-2.1-i2i": Workflow(
        name="qwen-image-2.1-i2i",
        template="recreation_qwen21_i2i.json",
        guide=("1", "image"), composite=("2", "image"), mask=("3", "image"),
        reference_inputs=(("9", "images.image_1"),),
        positive=("9", "prompt"), negative=("9", "negative_prompt"), seed=("13", "seed"),
        save="15",
        model_files=(("diffusion_models", "5", "unet_name"),
                     ("text_encoders", "4", "clip_name"),
                     ("vae", "6", "vae_name")),
        node_classes=("TextEncodeQwenImage21",) + MASK_CLASSES,
        reference="<image1>"),
}
DEFAULT_WORKFLOW = "qwen-image-2.1-i2i"   # chosen by the spike on 2026-09-24: 2511 drifts ~1 native px
REFERENCES = ("guide", "composite")


def load_template(workflow):
    """The `prompt` graph of the workflow's template file, read fresh."""
    path = Path(workflow.template)
    if not path.is_absolute():
        path = REPO_DIR / path
    return json.loads(path.read_text())["prompt"]


def http_json(url, data=None, timeout=60, token=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode(errors="replace")[:2000]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason} for {url}: {detail}") from e


def is_up(url, http=http_json):
    try:
        http(f"{url}/queue", timeout=5)
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def free_models(url, http=http_json):
    http(f"{url}/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
         timeout=60)


def missing_model_files(workflow, comfy_dir):
    """Workflow model files absent from <comfy_dir>/models, as relative paths."""
    prompt = load_template(workflow)
    missing = []
    for folder, node, key in workflow.model_files:
        name = prompt[node]["inputs"][key]
        if not (Path(comfy_dir) / "models" / folder / name).is_file():
            missing.append(f"models/{folder}/{name}")
    return missing


def missing_nodes(workflow, url, http=http_json):
    """Node classes of the workflow that the running ComfyUI does not describe.

    GET /object_info/<class> answers {} for an unknown class; an HTTP error
    counts as unknown too, so an old checkout fails the preflight, not the render.
    """
    missing = []
    for cls in workflow.node_classes:
        try:
            info = http(f"{url}/object_info/{cls}", timeout=30)
        except (OSError, ValueError, RuntimeError):
            info = {}
        if not isinstance(info, dict) or cls not in info:
            missing.append(cls)
    return missing


def wait_history(url, prompt_id, http=http_json, timeout=HISTORY_TIMEOUT, sleep=time.sleep):
    deadline = time.monotonic() + timeout
    while True:
        hist = http(f"{url}/history/{prompt_id}")
        if prompt_id in hist:
            return hist[prompt_id]
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no history for {prompt_id} within {timeout}s")
        sleep(POLL_SECONDS)


def stage_input(source, stage_name, comfy_dir):
    """Copy `source` into ComfyUI's input folder as `stage_name`."""
    input_dir = Path(comfy_dir) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, input_dir / stage_name)


def execute(prompt, url, http, timeout, sleep, interrupt=False):
    """Queue `prompt` and return its history entry once it succeeded.

    Raises RuntimeError when ComfyUI reports a failed execution and
    TimeoutError when the history never appears. With `interrupt`, a timeout
    or a KeyboardInterrupt while waiting first asks ComfyUI to stop the prompt
    (best effort: a failed interrupt must not hide the original exception).
    """
    resp = http(f"{url}/prompt", json.dumps({"prompt": prompt}).encode())
    try:
        entry = wait_history(url, resp["prompt_id"], http, timeout, sleep)
    except (TimeoutError, KeyboardInterrupt):
        if interrupt:
            try:
                http(f"{url}/interrupt", json.dumps({"prompt_id": resp["prompt_id"]}).encode())
            except Exception:
                pass
        raise
    status = entry.get("status", {})
    if status.get("status_str") != "success":
        raise RuntimeError(f"ComfyUI execution failed: {status.get('messages', status)}")
    return entry


def output_path(comfy_dir, img):
    """Where ComfyUI saved the output image `img` (a history `images[]` entry)."""
    return Path(comfy_dir) / "output" / (img.get("subfolder") or "") / img["filename"]


def render_window(workflow, *, guide, composite, mask, reference, positive, negative, seed,
                  name, url, comfy_dir, http=http_json, timeout=HISTORY_TIMEOUT,
                  sleep=time.sleep):
    """Queue one window render and return the path of the image ComfyUI saved.

    `guide`, `composite` and `mask` are local PNG paths, staged into ComfyUI's
    input folder as __atl_<name>_<part>.png. `reference` ("guide" or
    "composite") picks the image the encoder sees. The render lands in
    output/atl/ as <name>_NNNNN_.png; the caller moves it away and checks its
    size. Raises RuntimeError when ComfyUI reports a failed execution, and
    TimeoutError, after asking ComfyUI to interrupt the prompt, when no history
    appears in time; a KeyboardInterrupt while waiting interrupts the prompt too.
    """
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {', '.join(REFERENCES)}, got {reference!r}")
    comfy_dir = Path(comfy_dir)
    prompt = load_template(workflow)
    for (node, key), path, part in ((workflow.guide, guide, "guide"),
                                    (workflow.composite, composite, "composite"),
                                    (workflow.mask, mask, "mask")):
        staged = f"__atl_{name}_{part}.png"
        stage_input(path, staged, comfy_dir)
        prompt[node]["inputs"][key] = staged
    source = (workflow.guide if reference == "guide" else workflow.composite)[0]
    for node, key in workflow.reference_inputs:
        prompt[node]["inputs"][key] = [source, 0]
    for (node, key), value in ((workflow.positive, positive), (workflow.negative, negative),
                               (workflow.seed, seed)):
        prompt[node]["inputs"][key] = value
    prompt[workflow.save]["inputs"]["filename_prefix"] = f"{OUTPUT_PREFIX}/{name}"
    # A timed-out or Ctrl-C'd render is still running in ComfyUI; interrupt it so
    # it does not hold the queue (and ~45 GB) and write a file nobody collects.
    entry = execute(prompt, url, http, timeout, sleep, interrupt=True)
    return output_path(comfy_dir, entry["outputs"][workflow.save]["images"][0])


def sweep_outputs(room_key, comfy_dir):
    """Delete the room's leftover window renders under output/atl/, named as
    SaveImage names them: <room_key>_a<attempt>-<label>_NNNNN_.png. Returns the
    count.

    A failed room may leave renders ComfyUI finished after the driver gave up;
    room keys are room_NNN, so one room's pattern never matches another's.
    """
    folder = Path(comfy_dir) / "output" / OUTPUT_PREFIX
    pattern = re.compile(rf"^{re.escape(room_key)}_[A-Za-z0-9-]+_\d{{5}}_\.png$")
    removed = 0
    if folder.is_dir():
        for path in folder.iterdir():
            if pattern.match(path.name):
                path.unlink(missing_ok=True)
                removed += 1
    return removed
