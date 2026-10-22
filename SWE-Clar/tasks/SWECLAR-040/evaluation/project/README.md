# Object-store image grouping component

The benchmark must supply Node 22, AWS SDK S3/Rekognition clients pinned to 3.883.0 and the running synthetic provider before coding begins. Dependency installation is not part of this task. Start with `CATALOG_CONFIG=runtime/config.json CATALOG_STATE=runtime/state.json node server.cjs`; the server prints its loopback port as JSON. The prepared config contains bucket, collection, s3Endpoint, rekognitionEndpoint, poll_interval_ms and synthetic credentials:{accessKeyId,secretAccessKey}. No real service account is required.

Repair the existing single-owner local web component. Scan uses actual paginated ListObjectsV2; ingest fetches actual GetObject bytes, calls IndexFaces with a deterministic ExternalImageId and DEFAULT attributes, then SearchFaces for every indexed face. The fixture collection already exists. The test provider returns synthetic face IDs for generated geometric PNGs; this verifies AWS SDK serialization and integration, not real face recognition accuracy. No photographs of people, embeddings or original identity data are included.

The image reader, paginated listing, atomic storage helper and page shell are provided. Complete indexing, grouping, naming, search and periodic discovery. Poll automatically at the supplied interval, sharing the mutation queue with manual actions; recover from a failed poll on later cycles. Index each object key once and reuse repeated delivery. Group merging and name/search policies can be clarified. Only necessary image/FaceId associations and assigned names may be retained, never incidental FaceDetail attributes or credentials. A provider failure must not commit partial local records; external indexing may already have occurred. Replacing existing object content, production permissions, cloud event deployment and multi-user authentication are outside this local component.

GET /groups?q=..., GET /image?key=... and POST /action with type scan, ingest(key) or label(group_id,name) form the public local interface. Keep the object store/recognition adapters and page shell. Do not accept caller-supplied face lists or signatures as inference results.

`GET /groups` returns an array of objects with `group_id`, `name`, Boolean `named`, and `image_keys`. `POST /action` returns JSON on success; invalid operations return an error response. Image responses contain actual PNG/JPEG bytes and the corresponding media type. The development provider and its geometry images are independent fixtures, not hidden test data.

Preserve the supplied HTTP envelope: successful actions return 200; rejected actions return 400 with a JSON error object; unrecognized routes return 404. Ingest returns Boolean `duplicate` (true for an already indexed key). Group lists and image-key arrays may use any stable display order without duplicates. SDK image IDs must be deterministic and valid for the SDK, but no particular hash length or algorithm is required.

Run `node /public_tests/test_public.cjs` to check the prepared provider through real SDK listing, image retrieval, indexing and search. These checks do not solve the pending grouping policies. The prepared polling helper is provided; complete the scanned image operations. To start a fresh local application state, stop the application and launch it with a new `CATALOG_STATE` path inside `runtime/`; each benchmark attempt already receives a fresh workspace and provider.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
