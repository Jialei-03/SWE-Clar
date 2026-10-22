# Review assignment, fee allocation and approval-ledger module

Implement `process_review_action` in `solution.py` as a new domain-logic module. Process one listing, review application, acceptance, submission, payment, approval, profile-image, or deletion action into a new state without mutating inputs or exposing payment credentials. A reviewer may apply to an open listing; only the lister may accept one pending application, after which the listing waits for payment and the accepted review becomes the active review for that listing.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
