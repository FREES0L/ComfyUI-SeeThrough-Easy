"""Clean layer export for See-through parts.

Turns the parts the Post Process node returns into a ready-to-use layer set:

  * every layer is a full-canvas RGBA PNG, aligned with the input image
    (scaled to the working resolution), with the square padding cropped off;
  * layers are numbered back to front in a draw order that matches the input
    image (see ORDER MODES), not just See-through's per-part depth sort;
  * writes layers/NN-<part>.png, layers.json, composite.png, compare.png,
    contact-sheet.png, psd_info.json, <name>.psd (one layer per part, each
    cropped to its content and placed on the canvas) and a zip of all of it.

ORDER MODES
  depth       See-through's own rule: per-part depth median, far to near.
  face        depth, but the face parts form one block at the face's slot in
              anatomical order (ears < face < nose < mouth < eye white <
              irides < eyelash < eyebrow). Their depth medians sit within
              ~0.05 of each other, so pure depth order is noise there.
  visibility  (default) for every pair of parts that overlap, the part whose
              pixels match the input image in the overlap goes in front. The
              pairwise votes become a graph, sorted with depth as tiebreak;
              votes that would make a cycle are dropped, weakest first.
"""
import json
import math
import os
import re
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .seethrough_psd import write_psd

ORDER_MODES = ["visibility", "face", "depth"]

FACE_BLOCK = ["ears-l", "ears-r", "ears", "earl", "earr", "face", "nose", "mouth",
              "eyewhite-l", "eyewhite-r", "eyewhite", "irides-l", "irides-r", "irides",
              "eyes", "eyel", "eyer",
              "eyelash-l", "eyelash-r", "eyelash", "eyebrow-l", "eyebrow-r", "eyebrow",
              "browl", "browr"]

_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "see-through", "common", "assets", "arial.ttf")


def _font(sz):
    try:
        return ImageFont.truetype(_FONT_PATH, sz)
    except Exception:
        return ImageFont.load_default()


def _checker(w, h, s=16):
    yy, xx = np.mgrid[0:h, 0:w]
    c = (((xx // s) + (yy // s)) % 2).astype(np.uint8)
    img = np.where(c[..., None] == 1, 205, 245).astype(np.uint8)
    return Image.fromarray(np.repeat(img, 3, axis=2), "RGB")


def _slug(tag):
    return re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")


def _bbox(alpha):
    nz = np.argwhere(alpha > 0)
    if len(nz) == 0:
        return None
    (y1, x1), (y2, x2) = nz.min(0), nz.max(0) + 1
    return int(x1), int(y1), int(x2), int(y2)


def composite(parts, h, w):
    acc_rgb = np.zeros((h, w, 3), np.float64)
    acc_a = np.zeros((h, w, 1), np.float64)
    for p in parts:
        L = p["rgba"]
        al = L[..., 3:4] / 255.0
        acc_rgb = L[..., :3] / 255.0 * al + acc_rgb * (1 - al)
        acc_a = al + acc_a * (1 - al)
    rgb = np.where(acc_a > 0, acc_rgb / np.maximum(acc_a, 1e-8), 0)
    return (np.concatenate([rgb, acc_a], 2) * 255 + 0.5).clip(0, 255).astype(np.uint8)


def order_face(parts):
    if not any(p["part"] == "face" for p in parts):
        return parts
    block = sorted([p for p in parts if p["part"] in FACE_BLOCK], key=lambda p: FACE_BLOCK.index(p["part"]))
    rest = [p for p in parts if p["part"] not in FACE_BLOCK]
    fd = next(p["depth"] for p in parts if p["part"] == "face")
    idx = next((i for i, p in enumerate(rest) if p["depth"] < fd), len(rest))
    return rest[:idx] + block + rest[idx:]


def order_visibility(parts, src, min_px=150, margin=24, share=0.6):
    """parts: sorted back to front. Returns (ordered parts, vote log)."""
    n = len(parts)
    S = src.astype(np.int32)
    votes = []  # (weight, back_idx, front_idx)
    for i in range(n):
        for j in range(i + 1, n):
            bi, bj = parts[i]["bbox"], parts[j]["bbox"]
            x1, y1 = max(bi[0], bj[0]), max(bi[1], bj[1])
            x2, y2 = min(bi[2], bj[2]), min(bi[3], bj[3])
            if x2 <= x1 or y2 <= y1:
                continue
            Li = parts[i]["rgba"][y1:y2, x1:x2].astype(np.int32)
            Lj = parts[j]["rgba"][y1:y2, x1:x2].astype(np.int32)
            M = (Li[..., 3] >= 200) & (Lj[..., 3] >= 200)
            if M.sum() < min_px:
                continue
            s = S[y1:y2, x1:x2][M]
            ei = np.abs(Li[..., :3][M] - s).sum(1)
            ej = np.abs(Lj[..., :3][M] - s).sum(1)
            vi, vj = int((ei + margin < ej).sum()), int((ej + margin < ei).sum())
            if vi + vj < min_px // 2:
                continue
            f = vi / (vi + vj)
            if f >= share:
                votes.append((vi - vj, j, i))
            elif f <= 1 - share:
                votes.append((vj - vi, i, j))
    votes.sort(reverse=True)
    adj = {k: set() for k in range(n)}

    def reaches(a, b):
        stack, seen = [a], set()
        while stack:
            u = stack.pop()
            if u == b:
                return True
            if u in seen:
                continue
            seen.add(u)
            stack.extend(adj[u])
        return False

    kept, dropped = [], []
    for w, back, front in votes:
        if reaches(front, back):
            dropped.append((w, back, front))
            continue
        adj[back].add(front)
        kept.append((w, back, front))
    # Move parts only as far as a kept vote demands, so parts with no votes keep their slot.
    out = list(range(n))
    for _ in range(200):
        changed = False
        for w, back, front in kept:
            pb, pf = out.index(back), out.index(front)
            if pb > pf:
                out.pop(pb)
                out.insert(pf, back)
                changed = True
        if not changed:
            break
    else:
        print("[SeeThrough] visibility order did not settle; falling back to face order", flush=True)
        return parts, None
    log = {
        "kept": [f"{parts[b]['part']} < {parts[f]['part']} ({w})" for w, b, f in kept],
        "dropped_for_cycles": [f"{parts[b]['part']} < {parts[f]['part']} ({w})" for w, b, f in dropped],
    }
    return [parts[k] for k in out], log


def export_layers(tag2pinfo, resolution, source_rgb, out_dir, order="visibility", name="seethrough", save_psd=True):
    """Write the layer set into out_dir. source_rgb: HxWx3 uint8 input image. Returns layers.json content."""
    res = int(resolution)
    sh, sw = source_rgb.shape[:2]
    sz = max(sw, sh)
    px1, py1 = (sz - sw) // 2, (sz - sh) // 2  # same maths as center_square_pad_resize
    scale = sz / res
    cx1, cy1 = int(round(px1 / scale)), int(round(py1 / scale))
    cx2, cy2 = int(round((px1 + sw) / scale)), int(round((py1 + sh) / scale))
    cw, ch = cx2 - cx1, cy2 - cy1
    src_c = np.array(Image.fromarray(source_rgb).resize((cw, ch), Image.BOX))

    parts = []
    for tag, pinfo in tag2pinfo.items():
        img = pinfo.get("img")
        if img is None:
            continue
        if img.shape[-1] == 3:
            img = np.concatenate([img, np.full(img.shape[:2] + (1,), 255, np.uint8)], -1)
        x1, y1 = [int(v) for v in pinfo.get("xyxy", [0, 0, img.shape[1], img.shape[0]])[:2]]
        full = np.zeros((res, res, 4), np.uint8)
        hh, ww = img.shape[:2]
        sx1, sy1 = max(0, -x1), max(0, -y1)
        dx1, dy1 = max(0, x1), max(0, y1)
        dx2, dy2 = min(res, x1 + ww), min(res, y1 + hh)
        if dx2 <= dx1 or dy2 <= dy1:
            continue
        full[dy1:dy2, dx1:dx2] = img[sy1:sy1 + (dy2 - dy1), sx1:sx1 + (dx2 - dx1)]
        layer = full[cy1:cy2, cx1:cx2].copy()
        layer[layer[..., 3] == 0, :3] = 0
        bb = _bbox(layer[..., 3])
        if bb is None:
            continue
        parts.append({"part": tag, "depth": float(pinfo.get("depth_median", 1.0)), "rgba": layer, "bbox": bb})

    parts.sort(key=lambda p: p["depth"], reverse=True)  # far -> near
    order_log = None
    if order == "face":
        parts = order_face(parts)
    elif order == "visibility":
        parts = order_face(parts)
        parts, order_log = order_visibility(parts, src_c)

    lay_dir = os.path.join(out_dir, "layers")
    os.makedirs(lay_dir, exist_ok=True)
    entries = []
    for idx, p in enumerate(parts):
        fname = f"{idx:02d}-{_slug(p['part'])}.png"
        Image.fromarray(p["rgba"], "RGBA").save(os.path.join(lay_dir, fname), optimize=True)
        x1, y1, x2, y2 = p["bbox"]
        entries.append({"file": f"layers/{fname}", "part": p["part"], "order": idx,
                        "bbox": [x1, y1, x2 - x1, y2 - y1], "depth": round(p["depth"], 4)})

    comp = composite(parts, ch, cw)
    comp_img = Image.fromarray(comp, "RGBA")
    comp_img.save(os.path.join(out_dir, "composite.png"), optimize=True)

    mask = comp[..., 3] >= 250
    err = float(np.abs(comp[..., :3].astype(np.int32) - src_c.astype(np.int32))[mask].mean()) if mask.any() else 0.0

    meta = {
        "canvas": {"width": cw, "height": ch},
        "source": {"width": sw, "height": sh, "scale_to_source": round(scale, 6),
                   "note": "multiply canvas coords by scale_to_source to land on the input image"},
        "working_square": {"resolution": res, "crop_xyxy": [cx1, cy1, cx2, cy2]},
        "order": "back_to_front",
        "order_mode": order,
        "sides": "-l / -r are the character's left / right (image right / left)",
        "depth_note": "depth = See-through per-part depth median, 0 near .. 1 far",
        "reconstruction_mae": round(err, 2),
        "layers": entries,
    }
    if order_log:
        meta["visibility_votes"] = order_log
    if save_psd:
        meta["psd"] = f"{name}.psd"
    with open(os.path.join(out_dir, "layers.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # compare: input | composite on grey | composite over input | difference
    src_img = Image.fromarray(src_c)
    grey = Image.new("RGB", (cw, ch), (128, 128, 128))
    grey.paste(comp_img, (0, 0), comp_img)
    over_src = src_img.copy()
    over_src.paste(comp_img, (0, 0), comp_img)
    diff = np.abs(np.asarray(over_src, np.int16) - src_c.astype(np.int16)).sum(2)
    diff_img = Image.fromarray(np.clip(diff * 2, 0, 255).astype(np.uint8), "L").convert("RGB")
    cmp_ = Image.new("RGB", (cw * 4 + 30, ch + 40), (30, 30, 30))
    d = ImageDraw.Draw(cmp_)
    f = _font(22)
    for k, (im, label) in enumerate([(src_img, "input"), (grey, "layers stacked"),
                                     (over_src, "layers over input"), (diff_img, "difference x2")]):
        cmp_.paste(im, (k * (cw + 10), 40))
        d.text((k * (cw + 10) + 8, 8), label, fill=(240, 240, 240), font=f)
    cmp_.save(os.path.join(out_dir, "compare.png"), optimize=True)

    # contact sheet: every layer on a checkerboard, with its name
    tile, cols = 300, 6
    rows = max(1, math.ceil(len(entries) / cols))
    sheet = Image.new("RGB", (cols * tile, rows * (tile + 34)), (25, 25, 25))
    d = ImageDraw.Draw(sheet)
    f = _font(16)
    for k, (e, p) in enumerate(zip(entries, parts)):
        x, y, w, h = e["bbox"]
        m = 6
        sub = Image.fromarray(p["rgba"][max(0, y - m):y + h + m, max(0, x - m):x + w + m], "RGBA")
        sc = min((tile - 8) / sub.width, (tile - 8) / sub.height)
        sub = sub.resize((max(1, int(sub.width * sc)), max(1, int(sub.height * sc))), Image.LANCZOS)
        bg = _checker(tile - 4, tile - 4, 12)
        bg.paste(sub, ((bg.width - sub.width) // 2, (bg.height - sub.height) // 2), sub)
        ox, oy = (k % cols) * tile, (k // cols) * (tile + 34)
        sheet.paste(bg, (ox + 2, oy + 32))
        d.text((ox + 6, oy + 6), f"{e['order']:02d} {e['part']}  {w}x{h}px", fill=(235, 235, 235), font=f)
    sheet.save(os.path.join(out_dir, "contact-sheet.png"), optimize=True)

    if save_psd:
        write_psd(os.path.join(out_dir, f"{name}.psd"), cw, ch,
                  [(p["part"], p["rgba"][p["bbox"][1]:p["bbox"][3], p["bbox"][0]:p["bbox"][2]],
                    p["bbox"][0], p["bbox"][1]) for p in parts],
                  comp)

    # zip of the whole set, handy for sending to someone
    zip_path = out_dir.rstrip("/\\") + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(out_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.join(name, os.path.relpath(full, out_dir)))

    print(f"[SeeThrough] Exported {len(entries)} layers to {out_dir} (order={order}, "
          f"reconstruction error {err:.2f}/255)", flush=True)
    return meta
