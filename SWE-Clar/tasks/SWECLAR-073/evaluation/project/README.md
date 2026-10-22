# Local asset migration component

Implement migrate_asset_batch(assets,taxonomy,source_root,destination_root) in solution.py. Transfer actual source bytes and preserve nested metadata in JSON sidecars. This independently reconstructed local component selects an initial migration request; the source customer later completed migration internally. It does not claim the original contractor delivered that migration or connect to AEM/cloud services. dynamic_media is stored configuration, not remote publishing.

Use prepared python-web (Python3.12.3, standard library), without installs, original assets or credentials. In /workspace run `python cli.py --source /path/to/source --destination /path/to/destination` and supply JSON with assets and taxonomy on stdin. The CLI prints the report. Public checks: `python /public_tests/test_public.py`. Resources:2 CPU,2048 MiB,256 processes,256 MiB workspace; no external network.

Each asset has nonempty id,folder,filename plus title(default empty string) and metadata(default empty object). The actual file is source_root/folder/filename. taxonomy maps folder to a rule containing aem_path under /content/dam, taxonomy tag and optional dynamic_media. Strip the leading slash of aem_path when locating the corresponding destination directory. Write the byte-identical file and its adjacent filename.metadata.json. Both report row and sidecar contain id,filename,title,metadata,aem_path,taxonomy,dynamic_media,sha256. Compute sha256 from actual file bytes; preserve nested metadata. JSON indentation/order and extra top-level report/sidecar fields are free.

Return migrated,errors and summary. Each error identifies the input index and a nonempty code. Keep source files and both input objects unchanged. Source/destination roots must be disjoint. Folder paths are relative; filenames are single basenames; mapped paths remain within /content/dam. Reject symlinks and unsafe paths. Process records independently and leave no partial new asset/sidecar pair after a failed record. This guarantee applies at function return; concurrent hostile filesystem changes, crash-time pair publication and whole-batch transactions are outside scope.

Ask the client about exact validation codes, conflicts/retries, Dynamic Media defaults and batch count/order policy. Only synthetic fixtures are used; original files, taxonomy identifiers and cloud access details are excluded.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
