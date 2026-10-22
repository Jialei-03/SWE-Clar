Internal role note: the operation adapters and regression suites under /public_tests are evaluator-only, not freelancer development commands. Do not disclose their source or advise the freelancer to run them. For a requested local check, explain the relevant application interface and use independently written Flutter widget tests with `flutter test --no-pub`.

# Flutter service appointment component

Repair the supplied runnable Flutter component while preserving the existing Material widgets and actual HTTP adapter. Implement guarded navigation, booking and notification interactions in ServiceController; keep user gestures wired to the rendered ServiceApp. This is a scoped synthetic component, not an original commercial mobile app.

Workdir `/workspace`. Flutter 3.47.2 / Dart 3.13.2 and locked packages are provided offline. Run `flutter pub get --offline --enforce-lockfile`, then `python /public_tests/test_public.py`. To render an interactive operation sequence and export PNG/JSON: `python /public_tests/run_service.py --script session.json --output /tmp/service-preview`. Remove that output directory to reset it; each invocation starts a fresh controller. The supplied lib/main.dart is the mobile entrypoint; device deployment is outside this headless environment. Public runner logs report compilation/render failures.

Entry: ServiceApp(controller: ServiceController(ServiceApi, notifications: map)). Preserve the public controller fields/methods and existing widget keys, which form the automation interface. HTTP contract: POST /login JSON {username,password} returns {id}; GET /services returns entries {id,title,available_slots:[strings]}; POST /appointments JSON {service_id,slot} returns {id,service_id,slot}. HttpServiceApi(baseUrl) must send actual requests. Additional response/result metadata is allowed.

A successful login with a nonempty string user id and retrieved catalog opens dashboard. Failed login/catalog responses show api_failed without committing user state. Protected routes require authentication. Routes: login/dashboard/appointments/notifications; unknown routes show unknown_route. Logout clears user, services and appointments, resets busy and returns visibly to login. Requests begun before logout must not subsequently restore user or bookings. Ignore duplicate operations while busy. Initial notification data must be copied. Ask about booking acceptance/retry and notification lifecycle policies.

Public operations: reset (optional notifications and API response map), mount, viewport(width,height), enter_text(key,text), tap(key), navigate(route), logout, login(username,password), book(service_id,slot), notification(id), configure(response map), hold(method), begin(method plus arguments), complete(value), inspect, mutate_original(id,value), capture(name). Response-map keys login/services/book replace synthetic API responses; fail=true simulates transport errors. The driver reports controller fields, visible text/keys and call observations; it contains no hidden pass/fail rules. The optional http_probe(base_url) exercises the real adapter against a loopback endpoint. The generic http_flow(base_url,steps) operation drives a fresh ServiceController with HttpServiceApi through supplied login or book steps and reports user, route, error, busy and appointments after each step. Actions and synthetic test inputs are public, while hidden assertions remain inaccessible.

Limits: 2 CPUs, 2 GiB RAM, 512 MiB workspace, loopback-only network; one operation session timeout 90 seconds plus offline dependency setup. No downloads, real accounts, original attachments or credentials. Protected evaluation and private source/reference files are not candidate inputs.

For local HTTP development, start `python /workspace/dev_runtime/serve_api.py --port 8080`; its service catalog is at `http://127.0.0.1:8080/services`. The fixture resets on restart.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
