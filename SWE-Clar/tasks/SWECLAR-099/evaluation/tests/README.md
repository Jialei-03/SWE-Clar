# Private photo-chat checks

One gate per RU. backend_contract.py checks actual authenticated HTTP, JPEG pixels/metadata, real three-second countdown and 60-second late response, selected contacts, route validation and SQLite/assets persistence across an actual restart. test_solution.py also drives Chromium for login, request creation/open/upload, decoded image pixels, route/contact UI and two-column group geometry. Candidate server and Chromium run as UID 1000 with an allowlisted environment; assertions stay in the private verifier. All processes run in Linux Docker.
