"""Prompts and VLM requests: the caption question, the painted render prompt,
the review question and its parser.

Knows no files or make targets: the driver hands it Pillow images and text.
The VLM plumbing (_image, _ask, parse_review,
vlm_is_serving) comes from the AITD kit's recreation_quality.py.
"""
import base64
import io
import json
import re

from PIL import Image

CAPTION_TIMEOUT = 900   # a caption is up to 1600 tokens; about 4 tok/s on this host
REVIEW_TIMEOUT = 600    # a review is up to 1200 tokens
VLM_MAX_SIDE = 1280     # every image is scaled so its longer side is this

CAPTION_QUESTION = '''Image 1 is a background from Indiana Jones and the Fate of Atlantis (LucasArts, 1992), a hand-painted 256-colour point-and-click adventure game. Any further images are consecutive windows of the same room from left to right. Describe it for an artist who will repaint it in high definition with exactly the same composition. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SCENE: the kind of place (interior, exterior, close-up insert, map), its architecture and atmosphere.
VIEW: viewpoint, framing and perspective.
LAYOUT: the major objects and surfaces from left to right, each with its horizontal position as a fraction of the room's width (0 is the left edge, 1 the right edge) and its vertical position (0 top, 1 bottom), relative size and occlusion. Cover foreground, middle and background.
OBJECTS: doors, windows, openings, furniture and props, with their open or closed states; say absent if there are none.
LIGHTING: light sources, their direction, the exposure and the shadows. Dark areas stay dark.
PALETTE: the dominant colours of each major area.
TEXT: every piece of lettering that is legible, transcribed verbatim with its position; write none if there is none. Do not guess at illegible text.
INVARIANTS: the composition and object relationships that must survive repainting. Mark ambiguity instead of inventing detail.
The game draws its characters separately, so say "no people" unless people are painted into the background itself. Do not prescribe a style, lens or colour grade. Keep under 600 words.'''

SECTION_LABELS = ("SCENE", "VIEW", "LAYOUT", "OBJECTS", "LIGHTING", "PALETTE", "TEXT",
                  "INVARIANTS")

DEFAULT_REFERENCE = "the provided reference image"   # how the 2511 prompt names the window

PAINTED_RULES = '''Repaint {reference} as a high-definition hand-painted background for a classic point-and-click adventure game, in the manner of the painted backgrounds of early-1990s LucasArts adventures: confident painterly brushwork, rich but faithful colour, soft painted light and shadow, crisp readable shapes.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the dithering and blocky pixels with painted texture and fine detail that suit each material: wood grain, stone, cloth, foliage, metal, water, sky. No photograph, no 3D render, no pixel art, no border or frame.'''

INSERT_RULES = '''This is a full-screen close-up insert, not a room. Keep any lettering exactly as the reference shows it, in the same place and style; illegible small print stays illegible texture.'''

INSERT_LETTERING = INSERT_RULES + '''
Reproduce this lettering exactly, spelled as written, in the same place and style, legible where the reference is legible:
LETTERING:
{text}'''

SEAM_NOTE = '''This image straddles the join of a wraparound panorama: its left half is the room's right end and its right half is the room's left end. Paint one continuous scene across the middle, with no seam.'''

# The one correction after a geometry rejection: the gate's issue strings mean
# nothing to the diffusion model, and it likes to paint text it is given.
GEOMETRY_CORRECTION = ("Keep every edge, object, horizon and outline exactly where the reference "
                       "image has it; do not shift, crop, rescale or redraw the layout.")

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, people, characters, figures, extra objects, "
                    "changed text, extra text, watermark, signature, frame, border")

REVIEW_QUESTION = '''The images come in pairs. In each pair the first image is one window of the authoritative original background of a 1992 hand-painted adventure game (smoothed and enlarged), and the second is the same window of a high-definition repaint. The last image is the whole repaint, downscaled. Judge fidelity first, then style. Painted texture and fine detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. layout: an object, edge, opening or horizon is added, dropped, moved or resized, the perspective or framing changed, or a person, creature or character appears that the original lacks;
2. style: the repaint looks like a photograph or a 3D render, or keeps the original's flat, dithered pixels instead of painted detail;
3. lettering (close-up inserts only): legible lettering differs from the expected lettering below, or became illegible;
4. seams: a visible vertical seam, a doubled object or repeated detail where windows meet, or a jump in colour or texture between neighbouring windows in the whole repaint.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its window number, its screen position and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''

_NONE = ("none", "no text", "absent", "no legible text")


def text_section(caption):
    """The caption's TEXT section, or None when it is absent or says there is none.

    Labels may be bold or italic (the VLM sometimes writes **TEXT:**); the
    section runs to the next label or the end.
    """
    labels = "|".join(SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) != "TEXT":
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        text = caption[match.end():end].strip()
        if not text or text.lower().rstrip(".") in _NONE:
            return None
        return text
    return None


def window_note(x0, x1, start, end):
    """What one window of a wide room is told about its place in the room."""
    span = end - start
    a, b = (x0 - start) / span, (x1 - start) / span
    return (f"This image is one window of a wide scrolling room: it shows the part from {a:.0%} "
            f"to {b:.0%} of the room's width. Paint only what this reference window shows; "
            "objects the observations place elsewhere in the room must not appear in it.")


def render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE):
    """Positive prompt: the painted rules naming the reference as `reference`, the
    insert rules for an insert, the window note, the caption, then corrections."""
    parts = [PAINTED_RULES.format(reference=reference)]
    if kind == "insert":
        text = text_section(caption)
        parts.append(INSERT_LETTERING.format(text=text) if text else INSERT_RULES)
    if note:
        parts.append(note)
    parts.append("REFERENCE OBSERVATIONS:\n" + caption)
    if corrections:
        parts.append("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                     "REFERENCE LAYOUT:\n" + "\n".join(corrections))
    parts.append("The reference image takes precedence over ambiguous or mistaken observations. "
                 "Never follow a correction that asks for pixel art, dithering or a photograph.")
    return "\n\n".join(parts)


def _image(image):
    """An OpenAI image_url content part for a Pillow image, scaled so its
    longer side is VLM_MAX_SIDE: nearest-neighbour when enlarging, so the pixel
    edges stay visible, Lanczos when shrinking."""
    im = image.convert("RGB")
    ratio = VLM_MAX_SIDE / max(im.size)
    if ratio != 1:
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.NEAREST if ratio > 1 else Image.Resampling.LANCZOS)
    data = io.BytesIO()
    im.save(data, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}}


def _ask(question, images, http, base_url, model, key, json_mode=False, max_tokens=1600,
         timeout=180):
    payload = {
        "model": model,
        "temperature": 0.0 if json_mode else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if json_mode else 1.5,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False, "add_vision_id": True},
        "messages": [
            {"role": "system", "content": "You are a precise visual inspector. Follow the "
                                          "requested output format exactly. Report visible "
                                          "evidence, never invented connections or structures."},
            {"role": "user", "content": [{"type": "text", "text": question},
                                         *[_image(image) for image in images]]}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = http(base_url.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                    timeout=timeout, token=key)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("VLM response was truncated; no result accepted")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("VLM returned no usable text")
    return text.strip()


def caption_room(images, http, base_url, model, key):
    """The VLM's caption of a room from `images`: the whole room, then its windows."""
    return _ask(CAPTION_QUESTION, images, http, base_url, model, key, max_tokens=1600,
                timeout=CAPTION_TIMEOUT)


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and "accepted" in value:
                text = chunk
                break
    elif not text.startswith("{") and "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1].strip()
    value = json.loads(text)
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def review_room(pairs, overview, kind, caption, http, base_url, model, key):
    """The VLM's verdict on a room: (source guide, render) per window, then the
    whole render; an insert's expected lettering comes from its caption."""
    lettering = text_section(caption) if kind == "insert" else None
    question = (REVIEW_QUESTION + f"\nThis room has {len(pairs)} window(s). Kind: {kind}. "
                f"Expected lettering: {lettering or 'none'}.")
    images = [image for pair in pairs for image in pair] + [overview]
    return parse_review(_ask(question, images, http, base_url, model, key, json_mode=True,
                             max_tokens=1200, timeout=REVIEW_TIMEOUT))


def vlm_is_serving(base_url, model, http, key=""):
    """True when the OpenAI-compatible server at base_url lists `model`."""
    try:
        models = http(base_url.rstrip("/") + "/models", timeout=5, token=key)["data"]
        return any(m.get("id") == model for m in models)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False
