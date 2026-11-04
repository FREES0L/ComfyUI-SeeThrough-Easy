"""Model downloads for ComfyUI-SeeThrough-Easy.

Every model lands in plain folders under ComfyUI/models/SeeThrough/, not in a
hidden cache, so a user can see what was downloaded, copy it to another
machine, or delete it. Downloads resume after an interruption and are skipped
once a folder is complete.

Used two ways:
  * by nodes.py inside ComfyUI, on first use of a loader node;
  * as a script by the Windows installer, to fetch everything up front:
        python seethrough_models.py --models-dir <ComfyUI>/models/SeeThrough [--variant bf16|nf4|both]
"""
import argparse
import os
import shutil
import sys
import time
import urllib.request

LAYERDIFF_REPO = "layerdifforg/seethroughv0.0.2_layerdiff3d"
DEPTH_REPO = "layerdifforg/seethroughv0.0.1_marigold"
LAYERDIFF_NF4_REPO = "24yearsold/seethroughv0.0.2_layerdiff3d_nf4"
DEPTH_NF4_REPO = "24yearsold/seethroughv0.0.1_marigold_nf4"

# Approximate sizes, only for the messages users see.
REPO_SIZES_GB = {
    LAYERDIFF_REPO: 9.5,
    DEPTH_REPO: 3.1,
    LAYERDIFF_NF4_REPO: 3.8,
    DEPTH_NF4_REPO: 1.9,
}

LAMA_URL = "https://huggingface.co/dreMaz/AnimeMangaInpainting/resolve/main/lama_large_512px.ckpt"
LAMA_FILE = os.path.join("lama", "lama_large_512px.ckpt")

COMPLETE_MARKER = ".seethrough_complete"


def repo_dir(models_dir, repo_id):
    """Folder a repo is stored in: models/SeeThrough/<repo name without the org>."""
    return os.path.join(models_dir, repo_id.split("/")[-1])


def _marker_repo(path):
    try:
        with open(os.path.join(path, COMPLETE_MARKER), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def is_complete(path, repo_id=None):
    """True when path holds a finished model. With repo_id, a folder this tool
    downloaded must also have come from that exact repo, so a same-named repo
    from another owner never gets mixed up with it."""
    marker = _marker_repo(path)
    if marker is not None:
        return repo_id is None or marker == repo_id
    # folders a user placed by hand (git clone, copied from another PC)
    unet = os.path.join(path, "unet")
    return (os.path.isfile(os.path.join(path, "model_index.json")) and os.path.isdir(unet)
            and any(f.endswith(".safetensors") for _, _, fs in os.walk(unet) for f in fs))


def ensure_repo(models_dir, repo_id):
    """Download a Hugging Face repo into models_dir unless it is already there. Returns its folder."""
    target = repo_dir(models_dir, repo_id)
    if is_complete(target, repo_id):
        return target
    other = _marker_repo(target)
    if other is not None and other != repo_id:
        # same folder name, different owner: keep both apart
        target = os.path.join(models_dir, repo_id.replace("/", "__"))
        if is_complete(target, repo_id):
            return target
    from huggingface_hub import snapshot_download

    size = REPO_SIZES_GB.get(repo_id)
    size_txt = f" (about {size} GB)" if size else ""
    print(f"[SeeThrough] Downloading {repo_id}{size_txt} to {target}", flush=True)
    print("[SeeThrough] This happens once. If it gets interrupted, run again and it resumes.", flush=True)
    os.makedirs(target, exist_ok=True)
    last_err = None
    for attempt in range(1, 6):
        try:
            snapshot_download(repo_id=repo_id, local_dir=target, max_workers=4)
            break
        except Exception as e:  # network hiccups: retry, keep what is already on disk
            last_err = e
            wait = 5 * attempt
            print(f"[SeeThrough] Download attempt {attempt} failed: {e}. Retrying in {wait}s...", flush=True)
            time.sleep(wait)
    else:
        raise RuntimeError(f"Could not download {repo_id}: {last_err}")
    with open(os.path.join(target, COMPLETE_MARKER), "w") as f:
        f.write(repo_id + "\n")
    print(f"[SeeThrough] {repo_id} ready.", flush=True)
    return target


def ensure_lama(models_dir):
    """Download the LaMa inpainting checkpoint used to split front and back hair."""
    target = os.path.join(models_dir, LAMA_FILE)
    if os.path.isfile(target):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    print(f"[SeeThrough] Downloading LaMa inpainting model (about 0.2 GB) to {target}", flush=True)
    part = target + ".part"
    last_err = None
    for attempt in range(1, 6):
        try:
            start = os.path.getsize(part) if os.path.isfile(part) else 0
            req = urllib.request.Request(LAMA_URL, headers={"Range": f"bytes={start}-"} if start else {})
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if start and r.status == 206 else "wb"
                with open(part, mode) as f:
                    shutil.copyfileobj(r, f, 1024 * 1024)
            os.replace(part, target)
            break
        except Exception as e:
            last_err = e
            print(f"[SeeThrough] LaMa download attempt {attempt} failed: {e}. Retrying...", flush=True)
            time.sleep(5 * attempt)
    else:
        raise RuntimeError(f"Could not download the LaMa model: {last_err}")
    print("[SeeThrough] LaMa model ready.", flush=True)
    return target


def ensure_all(models_dir, nf4=False):
    repos = [LAYERDIFF_NF4_REPO, DEPTH_NF4_REPO] if nf4 else [LAYERDIFF_REPO, DEPTH_REPO]
    for repo in repos:
        ensure_repo(models_dir, repo)
    # LaMa is not fetched here: the default (v3) model splits front and back
    # hair itself, so LaMa only runs for older v2 checkpoints, on demand.


def main():
    ap = argparse.ArgumentParser(description="Download the See-through models into ComfyUI/models/SeeThrough.")
    ap.add_argument("--models-dir", required=True, help="path to ComfyUI/models/SeeThrough")
    ap.add_argument("--variant", choices=["bf16", "nf4", "both"], default="bf16",
                    help="bf16: full models (12.6 GB). nf4: 4-bit models for Nvidia cards under 10 GB (5.7 GB).")
    a = ap.parse_args()
    if a.variant in ("bf16", "both"):
        ensure_all(a.models_dir, nf4=False)
    if a.variant in ("nf4", "both"):
        ensure_all(a.models_dir, nf4=True)
    print("[SeeThrough] All models downloaded.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
