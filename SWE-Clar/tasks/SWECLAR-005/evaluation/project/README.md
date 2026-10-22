# Cycle Calendar

Complete this independently reconstructed local browser journal. Preserve its working journal creation, input form, timeline and local storage; finish cycle planning, rotating prompts and browser reminder behavior. The supplied examples and phase lengths are synthetic software-test schedules. All code and text are independently authored.

## Prepared runtime and commands

The benchmark provides the `python-calendar` image with Python 3.12, SQLite, Playwright and full Chromium. No installation, account, phone, customer material or external connection is needed. Working directory: `/workspace`; limits: 2 CPUs, 2 GiB memory, 256 processes, 512 MiB workspace and loopback network only.

Start `python -m http.server 8000 --bind 127.0.0.1 --directory .`, open `http://127.0.0.1:8000`, and create a local journal. There is no build step. Stop the server with Ctrl-C. Public check: `python /public_tests/test_public.py`. Reset a disposable browser context or remove the `cycle-journals` localStorage key to start again. Journals persist across page reloads in the same browser origin and are separate local workspaces, with no remote authentication service.

For browser checks launch `p.chromium.launch(channel='chromium', headless=True)` and create a context with `permissions=['notifications']`. The protected manager preflight verifies actual `ServiceWorkerRegistration.showNotification` and `getNotifications` before your budget starts. The default Chromium headless shell has different notification behavior; use the published full Chromium channel. Permission may also be denied in business tests. No browser download or desktop configuration is part of your task. Tests use a controlled browser clock and may select a different browser time zone; application dates and reminder times use UTC.

## Planning interface

Export `buildCyclePlan(input)` from `/src/cycle-planner.js` as a JavaScript ES module. It must also drive the actual page. Do not mutate input; repeated identical input returns identical data.

Required input fields: `periodStart` and `asOf` as real canonical `YYYY-MM-DD` dates in 2000–2099, integer `cycleLength` from 8 to 60 inclusive, and integer `periodLength` from 1 to `cycleLength-6` inclusive. Optional `seed` is an integer in the signed 32-bit range, default 0. Optional `promptPools` is null or an object with any subset of the four keys `menstrual`, `follicular`, `ovulatory`, `luteal`. Each value is an array of up to 32 nonblank strings of at most 200 characters. Preserve the original prompt string, including surrounding spaces. Omitted/null pools and omitted phase arrays are empty. Reject unknown input/pool keys and invalid types, dates, ranges or strings by throwing `Error('invalid_input')`.

Return `{currentDay,currentPhase,cycleStart,timeline,recommendation}`. `currentDay` is a 1-based integer, `currentPhase` is one of those four labels, `cycleStart` is a canonical date, `timeline` contains `{day,date,phase}` records, and `recommendation` is a string or null. Timeline output may cross the input year boundary. Ask the client about exact phase allocation, cycle boundaries and prompt selection; these are frozen business decisions available through clarification.

## Browser and persistence interfaces

Preserve the labeled element IDs in `index.html`. Form `create-form` creates a journal from the trimmed `label` (1–60 characters), with a fresh nonempty unique ID, makes it active and clears the label field. Existing journals remain. `profile-select` changes the active journal and immediately loads its stored settings. Local journal labels are displayed as text.

Form `settings-form` contains `period-start`, `cycle-length`, `period-length`, `seed`, `prompt-pools` (JSON), `reminder-time` (`HH:mm` in UTC), and checkbox `reminders-enabled`. Successful submission validates and stores the whole settings object, recomputes the displayed calendar, and shows `saved` in `feedback`. An invalid form shows `invalid_input`, preserves stored settings and displayed results, and leaves the entered form values available for correction. A valid date correction must update the actual timeline and current day immediately and remain after reload. Setting changes in one journal must not change another journal.

`today`, `current-day`, `current-phase`, `cycle-start`, `recommendation` and `journal-title` show the active journal's actual plan for the current UTC date. An empty recommendation displays `No prompt for this phase`. The `timeline` contains one element per day in plan order, with `data-date`, `data-phase`, `data-day`, and `aria-current="date"` exactly on today's entry. Keep a horizontally scrollable timeline within the page, with usable labeled controls and no page-wide horizontal overflow at 375 px and 1280 px. Render all labels and prompts literally. The date and plan refresh after UTC midnight while the page stays open.

The compatibility storage key is `cycle-journals`, containing `{activeId,profiles}`. Each profile has `id`, `label`, `settings`, and `notifiedDays` (canonical UTC date strings). A settings object consists of the planning fields except `asOf`, plus `reminderTime` and boolean `remindersEnabled`. An absent or malformed storage value behaves as no journals; creating a new valid journal repairs that stored value. New journals use today's period start, cycleLength 28, periodLength 5, seed 0, reminderTime `08:00`, reminders disabled, and the independently supplied default prompt pools. Preserve the active selection and each journal's valid state across reloads.

## Real browser reminders

`enable-notifications` requests browser permission and displays `Notification.permission` in `permission`. Enabling scheduling is a separate checkbox setting. Register `/sw.js` and send actual service-worker browser notifications; a candidate-written message array or status label is insufficient. Notification title is `Cycle Calendar reminder`, body is the selected literal prompt, tag is `cycle:<profileId>:<UTC-date>`, and `data` contains `profileId`, `date` and `phase`. The `reminder-history` lists that journal's successfully notified dates.

The page checks reminder eligibility at least once per second while open. Ask the client about due times, missed days, permission recovery, empty pools, journal switches, settings corrections, repeat delivery and persistent deduplication. The delivery boundary is the actual browser notification service while the application page runs; there is no remote push infrastructure. Use real browser notification APIs in verification. Keep service-worker and page assets local and independently authored.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
