# Prepared Python vision environment

Build it with `python SWE-Clar/environments/build.py` (see the repository README), which prepares the base profiles automatically; no manual preparation step is needed.

The manager verifies pinned package digests and installs dependencies while building the image. Candidate runs require no download or setup. The profile provides Pillow, Tesseract with English/orientation data, a fixed DejaVu font, SQLite, Chromium and Playwright. Preflight performs real generated-image OCR and the base browser/HTTP checks. Each task may additionally require protected service/UI capability checks.

Debian package copyright/license files remain installed under `/usr/share/doc`; Pillow license files remain in its installed distribution. DejaVu font licensing is supplied by its package. No customer images, prompts or identities are part of this profile.
