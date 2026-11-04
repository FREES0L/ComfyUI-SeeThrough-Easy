# ComfyUI-SeeThrough-Easy

Turns one anime character picture into separate transparent layers (hair, face, eyes, clothes, arms and so on), ready for Photoshop, Live2D or a 2D rig.

This is an easy-to-install version of [jtydhr88/ComfyUI-See-through](https://github.com/jtydhr88/ComfyUI-See-through), which runs the [See-through](https://github.com/shitagaki-lab/see-through) research model ([paper](https://arxiv.org/abs/2602.03749)) in [ComfyUI](https://github.com/Comfy-Org/ComfyUI). It adds a one-step Windows installer, automatic model downloads, graphics-card-aware defaults and a cleaner layer export.

## Install on Windows

You need:

- Windows 10 or 11, 64-bit
- An **Nvidia** graphics card with 8 GB or more, or an **AMD Radeon RX 7000 / 9000** series card
- 16 GB of RAM or more (32 GB is comfortable)
- About 25 GB of free disk space on `C:`
- An up-to-date graphics driver ([Nvidia](https://www.nvidia.com/drivers), [AMD](https://www.amd.com/en/support/download/drivers.html))

Then:

1. Press the **Windows key**, type `powershell` and press **Enter**.
2. Copy this line, paste it into the blue window (right-click pastes) and press **Enter**:

   ```powershell
   irm https://raw.githubusercontent.com/FREES0L/ComfyUI-SeeThrough-Easy/master/windows/install.ps1 | iex
   ```

3. Wait. It downloads ComfyUI (about 2 GB) and the models (about 13 GB), which takes 10 to 60 minutes depending on the internet connection. If Windows asks for permission to install "Microsoft Visual C++", click **Yes**.
4. When it says **Done!**, there is a **SeeThrough** icon on the desktop.

Prefer double-clicking? Download [`Install-SeeThrough.bat`](https://raw.githubusercontent.com/FREES0L/ComfyUI-SeeThrough-Easy/master/windows/Install-SeeThrough.bat) (right-click the link, *Save link as*) and double-click it. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.

Everything goes into `C:\SeeThrough`. To uninstall, delete that folder and the two desktop icons.

If the install stops halfway (internet dropped, PC restarted), run the same line again. It picks up where it left off.

If the installer says it can't find a graphics card but there is one, name it in front of the same line: `$env:SEETHROUGH_GPU = "nvidia"; ` (or `"amd"`) followed by the `irm ...` line.

## Use it

1. Double-click **SeeThrough** on the desktop. A black window opens, then the browser. Keep the black window open while you work.
2. In the browser, press **W** (or click **Workflows** on the left) and open **SeeThrough-Easy**.
3. In the **Load Image** box, click *choose file to upload* and pick your picture. An example picture is already loaded if you want to try it first.
4. Press **Run** at the top.
5. Wait about 5 to 15 minutes, depending on the graphics card. The black window shows progress.

The results:

- **Download PSD** on the last box saves the layered PSD to your Downloads folder. The same PSD is also in the run's folder.
- The **SeeThrough results** icon on the desktop opens the output folder. Each run makes a `seethrough\seethrough_<date>_<time>` folder with:
  - `seethrough_<date>_<time>.psd` — the layered PSD, one layer per part, each cropped to the part and placed where it belongs
  - `layers\` — one PNG per part, all the same size as the picture, numbered back to front (`00` at the back)
  - `layers.json` — the part names, draw order and positions
  - `compare.png` — the input next to the stacked layers, to spot what's missing
  - `contact-sheet.png` — every layer on its own
  - and a `.zip` of all of it next to the folder, for sending to someone

### If something looks wrong

- **Horns, a hat, ears or hair tips are cut off in a straight line:** raise `head_crop_pad` in the **Generate Layers** box to 0.5–0.8.
- **A part is missing (a tail, an object):** change `seed` in **Generate Layers** to another number and run again.
- **Out of memory error:** close other programs (games, browsers with many tabs) and run again. On an Nvidia card under 10 GB, set `quant_mode` to `nf4` in both **Load** boxes.

## What this version adds

Compared with the original node pack:

- **Windows installer** (`windows/install.ps1`) that picks the right ComfyUI build for the graphics card: Nvidia (CUDA 13, or CUDA 12.6 for drivers older than 580) or AMD (ROCm). Tested on clean Windows machines by GitHub Actions on every change.
- **Models download into `ComfyUI/models/SeeThrough/`**, in plain folders, instead of a hidden cache. Downloads resume after an interruption and are skipped once complete. `python seethrough_models.py --models-dir <path>` fetches them up front.
- **`auto` defaults that fit the graphics card.** `group_offload: auto` keeps most of the model in system RAM on cards under 20 GB (a 12 GB card runs out of memory without it). `quant_mode: auto` uses the 4-bit models on Nvidia cards under 10 GB.
- **`head_crop_pad` on Generate Layers.** The second pass crops around the head with a 20% margin, which cuts off horns and tall hats. 0.5 fixes it; the bundled workflow uses 0.5.
- **SeeThrough Export Layers (clean)**, a new node. The original orders layers by one depth value per part, which puts eyelashes under the eye whites and ears in front of the face. This node orders every overlapping pair by which part actually matches the input picture, writes full-canvas PNGs with the padding cropped off, saves a layered PSD with every layer cropped to its part (`save_psd`, on by default, so runs queued through the API get one too), and has its own Download PSD button.
- **A ready workflow** with the settings above and a note explaining each step.
- Group offload follows ComfyUI's chosen device instead of a hardcoded `cuda`, `bitsandbytes` is optional (only needed for 4-bit mode, Nvidia only), and `diffusers>=0.37` is required so group offload is actually available.

## Manual install (any OS)

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/FREES0L/ComfyUI-SeeThrough-Easy
pip install -r ComfyUI-SeeThrough-Easy/requirements.txt
# optional, Nvidia only, for 4-bit mode:
pip install "bitsandbytes>=0.49.2"
```

Restart ComfyUI and open the workflow from *Templates → Custom nodes → ComfyUI-SeeThrough-Easy*. Don't install this next to the original ComfyUI-See-through pack; they register the same node names.

## Speed and memory

Measured on an RTX 4070 Super (12 GB) at 1280 px, bf16, group offload on: about 10 minutes per picture, 7.7 GB of video memory, about 11 GB of system RAM. The first run also downloads the models.

## Credits and licenses

- Node pack: [jtydhr88/ComfyUI-See-through](https://github.com/jtydhr88/ComfyUI-See-through), MIT. Its original README is in [README_UPSTREAM.md](README_UPSTREAM.md).
- See-through code (`see-through/`): [shitagaki-lab/see-through](https://github.com/shitagaki-lab/see-through), Apache 2.0.
- Models: [layerdifforg/seethroughv0.0.2_layerdiff3d](https://huggingface.co/layerdifforg/seethroughv0.0.2_layerdiff3d) and [layerdifforg/seethroughv0.0.1_marigold](https://huggingface.co/layerdifforg/seethroughv0.0.1_marigold), CreativeML OpenRAIL++-M. Commercial use is allowed under the license's use restrictions.
- Additions in this fork: MIT.
