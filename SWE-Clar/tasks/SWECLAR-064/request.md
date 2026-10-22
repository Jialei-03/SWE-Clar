# Event matching backend component

Implement `process_matchmaker_command(state, command) -> dict` in solution.py. This bounded module handles local OTP verification, profiles, event registration, match permissions, messages, blocking and report records. Preserve the supplied SQLite CLI. It is not a full dating application or an SMS/Firebase integration. Actor IDs and organizer context are supplied by a trusted upstream caller; this command interface does not authenticate a network session.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
