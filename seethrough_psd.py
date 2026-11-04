"""Minimal layered PSD writer: 8-bit RGB, RGBA pixel layers, RLE compression.

No dependencies beyond numpy, so the export node can write a PSD on any
install, including the Windows portable build, without the browser.

    write_psd(path, width, height, layers, composite)

layers: back to front, each (name, rgba, left, top) where rgba is an HxWx4
uint8 array already cropped to the layer's content and (left, top) is where
its top-left corner sits on the canvas. composite: HxWx4 uint8, the flattened
image that viewers without layer support (thumbnails, previews) show.
"""
import struct

import numpy as np


def _packbits_row(row):
    """PackBits-encode one row (1-D uint8 array). Runs of 3+ equal bytes become
    repeat packets; everything between them goes out as literal packets."""
    n = row.size
    out = bytearray()
    if n == 0:
        return bytes(out)
    # boundaries of runs of equal bytes
    change = np.flatnonzero(row[1:] != row[:-1]) + 1
    starts = np.concatenate(([0], change))
    lengths = np.diff(np.concatenate((starts, [n])))
    lit_start = 0
    for s, ln in zip(starts[lengths >= 3].tolist(), lengths[lengths >= 3].tolist()):
        # literal bytes before this run
        while lit_start < s:
            k = min(128, s - lit_start)
            out.append(k - 1)
            out += row[lit_start:lit_start + k].tobytes()
            lit_start += k
        v = int(row[s])
        left = ln
        while left > 0:
            k = min(128, left)
            if k < 3:  # a 1-2 byte tail of a long run: send as literal
                out.append(k - 1)
                out += bytes([v]) * k
            else:
                out.append(257 - k)  # -(k-1) as a signed byte
                out.append(v)
            left -= k
        lit_start = s + ln
    while lit_start < n:
        k = min(128, n - lit_start)
        out.append(k - 1)
        out += row[lit_start:lit_start + k].tobytes()
        lit_start += k
    return bytes(out)


def _rle_channel(plane):
    """RLE-encode a 2-D plane. Returns (row byte counts, data)."""
    rows = [_packbits_row(plane[y]) for y in range(plane.shape[0])]
    return [len(r) for r in rows], b"".join(rows)


def _pad(data, mult):
    return data + b"\0" * (-len(data) % mult)


def _pascal_name(name):
    raw = name.encode("latin-1", "replace")[:255]
    return _pad(bytes([len(raw)]) + raw, 4)


def _unicode_name_block(name):
    s = name.encode("utf-16-be")
    body = struct.pack(">I", len(s) // 2) + s  # count in UTF-16 code units
    body = _pad(body, 4)
    return b"8BIM" + b"luni" + struct.pack(">I", len(body)) + body


def write_psd(path, width, height, layers, composite):
    width, height = int(width), int(height)
    records = bytearray()
    channel_data = bytearray()
    for name, rgba, left, top in layers:
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
        h, w = rgba.shape[:2]
        left, top = int(left), int(top)
        chans = []
        for cid, ci in ((-1, 3), (0, 0), (1, 1), (2, 2)):
            counts, data = _rle_channel(rgba[..., ci])
            blob = struct.pack(">H", 1) + struct.pack(f">{len(counts)}H", *counts) + data
            chans.append((cid, blob))
        rec = struct.pack(">iiii", top, left, top + h, left + w)
        rec += struct.pack(">H", len(chans))
        for cid, blob in chans:
            rec += struct.pack(">hI", cid, len(blob))
        rec += b"8BIM" + b"norm" + struct.pack(">BBBB", 255, 0, 0, 0)
        extra = struct.pack(">I", 0)        # no layer mask
        extra += struct.pack(">I", 0)       # no blending ranges
        extra += _pascal_name(name)
        extra += _unicode_name_block(name)
        rec += struct.pack(">I", len(extra)) + extra
        records += rec
        for _, blob in chans:
            channel_data += blob

    # negative count: the first alpha channel holds the merged transparency
    layer_info = struct.pack(">h", -len(layers)) + bytes(records) + bytes(channel_data)
    layer_info = _pad(layer_info, 4)
    layer_and_mask = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)

    comp = np.ascontiguousarray(composite, dtype=np.uint8)
    assert comp.shape[:2] == (height, width), (comp.shape, width, height)
    # Photoshop stores the flat image blended over white; readers undo that
    # with the alpha channel, so store it the same way.
    a = comp[..., 3:4].astype(np.float32) / 255.0
    rgb = comp[..., :3].astype(np.float32) * a + 255.0 * (1.0 - a)
    comp = np.concatenate([(rgb + 0.5).clip(0, 255).astype(np.uint8), comp[..., 3:4]], 2)
    counts_all, data_all = [], []
    for ci in range(4):
        counts, data = _rle_channel(comp[..., ci])
        counts_all += counts
        data_all.append(data)

    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H", 1) + b"\0" * 6)
        f.write(struct.pack(">HIIHH", 4, height, width, 8, 3))  # 4 channels, 8-bit, RGB
        f.write(struct.pack(">I", 0))                            # color mode data
        f.write(struct.pack(">I", 0))                            # image resources
        f.write(struct.pack(">I", len(layer_and_mask)) + layer_and_mask)
        f.write(struct.pack(">H", 1))                            # merged image: RLE
        f.write(struct.pack(f">{len(counts_all)}H", *counts_all))
        for d in data_all:
            f.write(d)
