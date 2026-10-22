# Notebook bookmark extension

Complete the bookmark extension in this independently authored browser notebook host. The running project already has an editable synthetic notebook, HTTP/SQLite storage, a ribbon button, bookmark creation and nested folders. Complete movement, keyboard interaction and view preferences using the client's clarification. This is a standalone notebook extension exercise; it does not claim compatibility with any commercial note-taking application or include customer documents/code.

## Prepared environment

The benchmark provides Python 3.12, SQLite and Playwright/Chromium in a fixed Linux AMD64 image. Start from `/workspace` with `python server.py --port 8000 --db /tmp/notebook.sqlite`; open `http://127.0.0.1:8000`. A port of `0` selects an available loopback port, printed as a JSON line. Public checks: `python -I /public_tests/test_public.py`. No downloads, SDKs, accounts or external services are required. The manager performs independent HTTP/browser/database health checks before the agent budget.

Use a fresh database path to reset the synthetic notebook. Restart with the same path to reopen it. Tests allocate an independent database per case. Execution limits are 2 CPUs, 2 GiB RAM, 256 processes and 512 MiB workspace, with a 240-second evaluation limit. Keep the command-line interface and documented HTTP/UI entry points; internal implementation may change.

## Host and extension boundary

`host.js` renders an actual hierarchy of notebooks, groups, sections, pages and editable paragraphs. `model.py` owns document and bookmark operations. `server.py` stores the workspace in SQLite. `sidebar.js` and `styles.css` render and operate the extension. All document titles and paragraph text are invented fixtures. Bookmark targets are host object IDs; no arbitrary URL, original identifier or external navigation is needed.

The ribbon's Bookmarks button toggles the sidebar. Save current captures the selected ancestor type of the current host object (a paragraph has page/section/group/notebook ancestors). Opening a bookmark navigates this host and focuses the target paragraph when applicable. Paragraph edits must remain available after navigating away and restarting. Menu insertion stays open; an outside click dismisses it. No detached JSON result can substitute for working navigation, editing and sidebar interaction.

The sidebar exposes tabs, a nested tree, folder creation, in-cell rename, deletion confirmation, folder sorting, drag/drop, Ctrl/Shift selection, keyboard navigation, a resize separator and a right-click word-wrap option. The exact selection/movement/order, keyboard and persisted-view policies are client decisions. The source contains provisional implementations of several of these operations. Finish them without breaking the existing host or public regressions.

## Public HTTP contract

Responses are JSON, except static assets. `GET /api/state` returns `{tabs,active_tab,expanded,width,wrap}`. Each tab is `{id,name,items}`. A folder is `{id,kind:"folder",label,children}`; a bookmark is `{id,kind:"bookmark",label,target_id,target_type}`. `GET /api/document` returns `{nodes,current}`; nodes have `{id,parent,kind,text}`. The initial tab is `HOME`, initially no bookmarks/folders, width 280, wrap false, and current host object `PAR-A`.

`POST /api/host` accepts `{type:"navigate",id}` or `{type:"edit",id,text}` and returns the updated document. Only paragraphs are editable; text is at most 4000 characters. Navigating to non-paragraph objects shows their title and path. Navigating to a page/paragraph shows that page's editable paragraphs.

`POST /api/action` accepts one command and returns the updated bookmark state:

| Type | Fields |
|---|---|
| `bookmark` | `id,target_id,label?,tab_id?,parent_id?` |
| `folder` | `id,label,tab_id?,parent_id?` |
| `rename` | `id,label` |
| `delete` | `id,confirmed,recursive?` |
| `tab` | `id,name` |
| `activate` | `id` |
| `move` | `ids,tab_id,parent_id?,index?` |
| `sort` | `tab_id?,parent_id?` |
| `view` | `expanded?,width?,wrap?` |
| `open` | `id` |

IDs are nonempty ASCII letters/digits/underscore/hyphen, at most 64 characters. Item/tab IDs are globally unique. Labels are trimmed, 1–120 characters. A default bookmark label uses the first 120 characters of trimmed target text, or `Untitled` if empty. Target types come from real host nodes, not a client-supplied flag. Optional tab defaults to the active tab where shown; null/omitted parent means the tab root. Nested folders are supported without a task-specific depth restriction. Creation appends to its destination. Identical targets may have separate bookmark IDs. Rename changes the displayed bookmark/folder label, not the host content.

Deletion needs `confirmed:true`; a nonempty folder additionally needs `recursive:true`. The command fails otherwise. Invalid commands return HTTP 400 and `{error:<code>}`; unknown HTTP routes return 404. Whole-command rollback and specific invalid-move/view handling are available through clarification. Do not silently invent host targets or navigate to external URLs.

## Stable UI hooks

The existing entry points are `#toggle-sidebar`, `#sidebar`, `#target-kind`, `#add-bookmark`, `#new-folder`, `#new-tab`, `#tabs`, `#tree`, `#delete-item`, `#sort-items`, `#resize`, `#word-wrap`. Tree rows expose `[data-item]` and labels `.label`; tab buttons `[data-tab]`; host navigation `[data-object]` and editable paragraphs `[data-paragraph]`. Rename uses an input labeled `Rename item`. Preserve these hooks or equivalent accessible controls with these hooks so the published interaction harness can operate the actual UI. Content must render as text, including labels containing angle brackets.

All detailed policies are synthetic benchmark choices frozen before evaluation. The client can explain business behavior but does not provide hidden tests or reference code.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
