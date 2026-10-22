"""Export native API JSON, or submit it to the provided local ComfyUI server."""
import argparse,json
from pathlib import Path
from solution import build_portrait_workflow
from comfy_client import ComfyClient
parser=argparse.ArgumentParser();parser.add_argument('config');parser.add_argument('--submit');parser.add_argument('--output',default='workflow.json');args=parser.parse_args()
workflow=build_portrait_workflow(json.loads(Path(args.config).read_text()));Path(args.output).write_text(json.dumps(workflow,indent=2))
if args.submit:
    if 'error' in workflow:raise SystemExit(json.dumps(workflow))
    client=ComfyClient(args.submit);prompt_id=client.submit(workflow);print(json.dumps(client.wait(prompt_id)))
else:print(args.output)
