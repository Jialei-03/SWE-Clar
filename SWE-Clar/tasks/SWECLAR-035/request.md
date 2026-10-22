# Membership cart, coupon and credit-ledger policy module

Extend the provided local Python account library with cart, checkout, settlement and renewal behavior through `process_membership_action(state, action)`. Preserve caller inputs and unrelated state, and never retain raw card values. Account creation and inactivation are already implemented and must keep working.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
