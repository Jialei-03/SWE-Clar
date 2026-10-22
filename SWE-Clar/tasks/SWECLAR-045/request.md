# Event-credit accounting, refund and synchronization-ledger module

Implement `process_cashless_action` in `solution.py` as a new domain-logic module. Process one registration, card, payment, synchronization, or report action into a new state without mutating inputs. Register terminals by unique non-empty IMEI, create customers with unique IDs, and activate one unique NFC card for a known customer with zero balance.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
