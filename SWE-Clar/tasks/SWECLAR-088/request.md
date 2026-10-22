# SWECLAR-088

Implement the supplied persistent license backend. Process immutable purchase events into bound licenses and a real local email outbox, preserving SQLite CLI state across invocations and keeping raw secrets out of public results. The component also covers shop verification, secondary-use warnings, trial expiry and administrator search/status controls; clarify these policies as needed. This is a synthetic local component, without live email or commerce-platform integration.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
