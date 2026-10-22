# Prepared local ComfyUI

Pinned upstream ComfyUI v0.3.30 and IPAdapter Plus run on CPU. The wheel lock is complete for CPython3.12/linux x86_64. Models are public pretrained SD1.5, author Canny ControlNet, Plus-Face IPAdapter and CLIP Vision ViT-H. Every download is hash checked; ViT-H F32->F16 conversion is deterministic, with both digests recorded. Runtime includes model cards, CreativeML OpenRAIL-M and Apache notices, plus upstream code licenses. No customer assets, credentials or source-project code are included.

Build it with `python SWE-Clar/environments/build.py` (see the repository README), which prepares the base profiles automatically; no manual preparation step is needed. The build uses verified artifacts and then executes upstream object-info/native-queue image IO as UID1000. This IO check does not claim weighted portrait inference; the separate task reference/runtime evidence must demonstrate the full IPAdapter/ControlNet/sampling chain.

Use only an explicitly allocated exclusive benchmark stage: CPU2, maximum7GiB, no Docker resource reconfiguration. Model weights occupy about4.22GB; actual peak memory and short-step sampling time must be measured. Start services with writable input/output/temp/user directories, CPU fp16 UNet/text encoders and fp32 VAE; read-only models remain in /opt/comfy/models. No dependency install or network access during candidate attempts.

CPU compatibility: the pinned IPAdapter attention converts projected key/value tensors to the UNet query dtype before real attention. This fixes mixed Float/Half CPU execution without replacing weights, nodes, or sampling. `patch_ipadapter.py` verifies both source and patched SHA-256; the exact two-line numerical change is in `ipadapter-cpu.patch`.
