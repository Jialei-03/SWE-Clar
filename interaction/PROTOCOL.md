# Multi-cycle interaction protocols

The experimental design covers 100 tasks for each of two models (Luna max and GLM5.3 Flash max) under each of two protocols, totaling 400 task configurations. Client, Supervisor and Judge use Luna max; credentials are supplied through user-owned environment variables.

- `interleaved_clarify`: the candidate alternates client questions and implementation, carrying forward approved dialogue and its own code.
- `progressive_oracle`: start with the initial request and permitted workspace, then disclose one eligible hidden RU per cycle. The bundled dataset does not inject a formal RU checklist at initialization; the initial materials can still convey requirement information.

Each cycle freezes the same visible context and starting code for independent Audit and Coding branches. Audit answers and hidden-test feedback are not returned to the candidate. The 12-cycle cap is reported as budget exhaustion, not successful completion. Use the final result rather than selecting the best-scoring cycle or attempt.

This release uses the configured Pi provider; deployment-specific transports are not included. Record transport and model versions for new runs.
