# Hiring marketplace

Maintain a running independent local web application, preserving authentication, profiles and relationships while completing hiring workflows. All accounts, jobs and example resumes are synthetic. The complete job/application, interview and analytics decisions are available through clarification.

## Prepared execution

Work in `/workspace`. Python 3.12, SQLite 3.45, Chromium 140 and Playwright 1.55 are installed and protected. Resources: 2 CPUs, 2 GiB RAM, 256 processes, 512 MiB workspace and 1 GiB temporary storage; loopback HTTP is allowed, external networking is disabled. The benchmark runs an independent preflight before candidate work. There is no dependency installation or external account provisioning.

- Start: `python server.py --port 8000 --db hiring.sqlite --fixtures fixtures/demo.json`.
- Open `http://127.0.0.1:8000/` in the prepared browser.
- Public regression: `python /public_tests/test_public.py`.
- Stop with Ctrl-C. Restart using the same database to retain state; choose a new database path for a fresh demo.
- `--port 0` chooses a free port. Startup prints a JSON object with its numeric `port`. Application errors may be inspected on stderr; ordinary shell redirection can save a log.

The starter includes `server.py`, `storage.py`, `marketplace.py`, `web/` and `fixtures/demo.json`. Its server and SQLite database are the actual project; starting the app is normal development. Internal code structure is free, but preserve the command, public interfaces and business database columns described here.

## Fixtures and public formats

Fixture JSON supplies `clock_ms`, `users`, `jobs`, `relationships`, `resumes`, `applications`, `interviews` and `views`. The starter's demo illustrates each schema; evaluation uses independent fixtures with different IDs/content. `users` contain `{id,name,role,bio,password}` with roles `employer` and `employee`. Jobs use `{job_id,employer_id,title,description,category,location,active}`. Relationships use `{actor_id,target_id,kind}`. Resume fixture records use `{resume_id,owner_id,filename,content_base64}`. Applications use `{application_id,job_id,employee_id,resume_id,status}`; interviews use `{interview_id,application_id,start_ms,end_ms}`; views use `{viewer_id,event_id,job_id,timestamp_ms}`. Fixtures contain valid references, at most 30 users, 100 jobs, 200 applications/interviews and 5000 views. Runtime timestamps and `clock_ms` are integer Unix milliseconds in `[0,253402300799999]`, excluding booleans. IDs match `[A-Za-z0-9_-]{1,64}`.

Job title is at most 160 characters, description 10000, category/location 80; each must be trimmed nonempty Unicode text. Display names are trimmed nonempty text up to 120 characters; bio is literal text up to 2000 characters, including empty text. Names and descriptions can contain markup-like characters and must be displayed literally. JSON booleans are actual booleans. A resume is a UTF-8 text file of 1 through 262144 decoded bytes without NUL, sent as canonical standard base64 in JSON. Its ASCII basename is 1–80 characters, starts with a letter/digit, uses only letters/digits/spaces/underscore/hyphen/dot and ends in `.txt` (case-insensitive). Do not accept directory separators or use an uploaded name as a server path. The browser uses a real file input; exact decoded content must be downloadable. PDF parsing and third-party document storage are not needed.

SQLite tables are `meta`, `users`, `sessions`, `relationships`, `jobs`, `bookmarks`, `resumes`, `applications`, `interviews` and `views`. Keep existing named business columns, allowing harmless extra columns/tables. Resume `content` is a SQLite BLOB of the actual uploaded bytes; `size_bytes` and `sha256` describe it. Public flags `active` are stored as 0/1 and exposed as JSON booleans. Use real database persistence across server restart.

Demo accounts are `employer-a`, `employer-b`, `employee-a` and `employee-b`, each with password `local-demo`. These are synthetic local fixtures. Do not hard-code them; all identity and role authority comes from the actual validated session.

## HTTP interface

Use JSON objects with exactly the specified request fields and one value per query parameter; `?` fields marked optional may be omitted. Every API except login needs `Authorization: Bearer TOKEN`. Successful responses are JSON unless specified. Errors use an actual error HTTP status and `{"error":{"code":"..."}}`; exact code wording is free. Invalid sessions are 401, malformed input is 400, and workflow-specific denial/conflict/not-found statuses are clarifiable. Return harmless extra JSON metadata freely, but never credentials, password hashes or other sessions.

| Method/path | Request | Success shape |
|---|---|---|
| GET /health | none | `{ok:true}` |
| POST /api/login | `{id,password}` | `{token,user:{id,name,role,bio}}` |
| POST /api/logout | `{}` | `{ok:true}` |
| GET /api/me | none | `{user:{id,name,role,bio},clock_ms}` |
| GET /api/profiles | none | `{profiles:[{id,name,role,bio}]}` |
| PUT /api/profile | `{name,bio}` | `{user:{id,name,role,bio}}` |
| GET /api/relationships | none | `{relationships:[{actor_id,target_id,kind}]}` |
| POST /api/relationships | `{target_id,kind,enabled}` | `{relationships:[...]}` |
| GET /api/jobs | optional query `q,category,location` | `{jobs:[{job_id,employer_id,title,description,category,location,active}]}` |
| GET /api/job | query `job_id` | `{job:{...}}` |
| POST /api/jobs | `{job_id,title,description,category,location}` | `{job:{...}}` |
| PUT /api/jobs | `{job_id,title,description,category,location,active}` | `{job:{...}}` |
| GET /api/bookmarks | none | `{jobs:[{...}]}` |
| POST /api/bookmarks | `{job_id,enabled}` | `{jobs:[{...}]}` |
| POST /api/resumes | `{resume_id,filename,content_base64}` | `{resume:{resume_id,filename,size_bytes,sha256},duplicate:boolean}` |
| GET /api/resume | query `resume_id` | original file bytes, text/plain; attachment filename |
| GET /api/applications | none | `{applications:[{application_id,job_id,employee_id,employer_id,job_title,resume_id,status}]}` |
| POST /api/applications | `{application_id,job_id,resume_id}`; resume_id can be null | `{application:{...},duplicate:boolean}` |
| POST /api/reject | `{application_id}` | `{application:{...}}` |
| POST /api/interviews | `{interview_id,application_id,start_ms,end_ms}` | `{interview:{...},duplicate:boolean}` |
| GET /api/calendar | none | `{interviews:[{interview_id,application_id,job_id,job_title,participants,start_ms,end_ms}]}` |
| POST /api/views | `{event_id,job_id,timestamp_ms}` | `{accepted:true,duplicate:boolean}` |
| GET /api/analytics | query `job_id`; optional paired `start_ms,end_ms` | `{job_id,views,unique_viewers,by_day:[{day,views,unique_viewers}]}` |
| GET /api/analytics.csv | same query as analytics | CSV filename `job-views.csv`, header `day,views,unique_viewers` |

The public baseline relationships are directional follow (either role to another employer) and symmetric connect (employee to employee, immediate local contact creation). Self-relations are 400, missing targets 404 and invalid role pairs 403. enabled true/false idempotently adds/removes. Serialize connect with the smaller ID first and sort own involved relations by kind,actor_id,target_id. Profiles expose only public fields; profile editing cannot change ID/role.

## Browser contract

Retain these IDs on their corresponding controls. Internal markup/styles and non-contract labels are free. Use visible empty/error/pending states and allow retries. Clear old account data on logout/login and reject stale asynchronous results. Scrolling is allowed, with no horizontal overflow at 390x844 and 1280x900.

| IDs | Purpose |
|---|---|
| login-form, account, password, login-status | sign in and feedback |
| application, identity, logout, refresh, status | authenticated workspace and refresh feedback |
| profile-form, profile-name, profile-bio, profile-save, profiles | edit own profile and list public profiles; rows have data-profile-id |
| relationship-form, relation-target, relation-kind, relation-enabled, relationship-save, relationships | relation mutation and own relation list |
| job-form, job-id, job-title, job-description, job-category, job-location, job-active, job-save, job-status | create/edit selected own job; empty selection means create, selecting an existing row means edit |
| search-form, search-q, search-category, search-location, search, jobs, job-detail | discovery and selected job; each row has data-job-id and a data-action=open button |
| bookmark, bookmarks | toggle selected job bookmark and show saved jobs |
| resume-file, resume-id, upload-resume, resume-status | real file selection/upload and resulting or manually entered resume ID |
| application-id, apply, application-status, applications | apply to selected job; optional resume ID comes from resume-id; application rows have data-application-id and data-action=select |
| download-resume | download the selected application's attached resume |
| interview-id, interview-start, interview-end, schedule, reject, interview-status, calendar | selected application decisions and UTC ISO timestamp inputs; agenda entries have data-interview-id |
| analytics-job, analytics-start, analytics-end, analytics-load, analytics-status, analytics-summary, view-chart, analytics-download | job/period selection, actual SVG columns and CSV download; blank dates mean all-time |
| view-retry, view-status | retry an unsuccessful view event without changing its ID |

Use ISO strings with a UTC `Z` suffix in the time input controls; HTTP uses integer milliseconds. Empty selection for job creation can be obtained by clearing job-id; job-save creates if that ID is not among the displayed owned jobs, otherwise updates it. The saved active checkbox controls existing jobs. Opening an employee job submits a view at clock_ms; retry uses the same event ID. Distinct deliberate openings may generate distinct IDs. Each analytics day is represented by a rect[data-day] in svg#view-chart with readable day/count labels. Permission controls for hidden workflows should match their clarified server policies. The private reference and hidden tests are not application resources.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
