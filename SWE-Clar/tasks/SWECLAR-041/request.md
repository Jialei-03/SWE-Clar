# Portable controller firmware

Refactor this running C++ controller to implement the agreed LED timing, health-telemetry publication and safe command-handling rules. Preserve the event loop, virtual serial interface, actual registration listener, registration beacons and asynchronous telemetry-bus connection. Registration completion must close the listener and stop beacons without interrupting connectivity.

The local development environment and synthetic fixtures are prepared. Work in `/workspace`; no customer accounts or external deployment are required.
