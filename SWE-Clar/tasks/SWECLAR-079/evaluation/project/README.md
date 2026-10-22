# Local portrait workflow module

Complete `build_portrait_workflow(config)` in solution.py. It returns `{"prompt": {node_id: {"class_type": ..., "inputs": ...}}}` for the **ComfyUI API**, or `{"error": {"code": "nonempty string", ...}}` without a runnable prompt. Node IDs/order and additional metadata are unrestricted. Preserve the supplied config. This is an API export, not the separate visual-editor workflow JSON format.

The prepared python-comfy environment supplies ComfyUI v0.3.30, pinned IPAdapter Plus, CPU PyTorch and public pretrained SD1.5 / Canny ControlNet / Plus-Face IPAdapter / CLIP Vision weights. No package, model, image or account download is needed during an attempt. Native `/object_info`, `/prompt`, `/history` and `/view` are used; the included comfy_client.py is a loopback client, not an interpreter.

`python cli.py config.json --output workflow.json` exports the graph. Add `--submit http://127.0.0.1:8188` to submit it to the provided local server and wait for real execution. The runtime recipe contains the exact server launcher and model inventory. Public model/code licenses are included in that runtime.

Configuration fields:

- `template_asset`, `face_asset`: input filenames listed in `assets`.
- `prompt`, `negative_prompt`: nonempty text.
- `models`: checkpoint, controlnet, clip_vision and ipadapter filenames. `available_models` gives lists under checkpoints, controlnet, clip_vision and ipadapter. `available_nodes` comes from the actual server's object-info keys.
- `width`, `height`: requested saved-image dimensions. `sample_width`, `sample_height`: separate diffusion dimensions, at least64 and divisible by8.
- `face_crop`: x/y/width/height rectangle in source-face pixels. `edit_box`: x/y/width/height rectangle in output pixels.
- `seed`: nonnegative integer; `steps`: integer1–100; `vram_gb`: a workflow-selection hint, not container RAM.

Ask for the intended conditioning, output preservation and decode policies. The bounded integration uses synthetic drawings and a short CPU sampling pass, then a declared output resize. It does not score subjective face identity, pose accuracy, photorealism or seam quality, and does not establish native high-resolution generation. The execution allocation is at most7GiB RAM / CPU2; GPU-memory hints must not be confused with that budget.

Start the local server with `python /workspace/dev_runtime/start.py --root /tmp/comfy-demo --port 8188`; health is `GET http://127.0.0.1:8188/object_info`. Place local images in `/tmp/comfy-demo/input`. Run `python /public_tests/smoke.py` for the working inventory/CLI regression; it does not require a finished portrait graph.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
