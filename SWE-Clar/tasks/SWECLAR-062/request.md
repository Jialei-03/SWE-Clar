# Recurring service backend module

Implement `process_tasker_action(state, action) -> dict` in solution.py. Preserve the supplied SQLite command-line interface. This is a bounded web-backend policy component for quotes, monthly agreements, invoices, supplied payment events, categories and admin navigation records. It has no external payment provider, authentication service or full marketplace UI. Payment records never imply money was charged or settled.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
