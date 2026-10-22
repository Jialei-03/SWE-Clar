# Task contracts and information access

Each task's `evaluation/delivery_contract.json` binds requirement interfaces and acceptance sources to SHA256 hashes. Formal project documentation resides in evaluator-only `evaluation/project/`, not the initial candidate input. Client and Supervisor read the same private task requirements and agreement materials through restricted tools.

The candidate starts with the initial request and permitted workspace. A Client draft is reviewed by the Supervisor before delivery. Only approved replies reach the candidate. Internal drafts, review feedback and private evaluation materials remain separate. The active protocol does not automatically append interface specifications to approved replies; relevant interface details are conveyed through the reviewed response.

After clarification, the harness freezes the initial request, approved conversation and workspace observations. Audit and Coding start independently. Audit reads permitted materials and answers requirement questions; Coding edits and tests its implementation. Audit answers and hidden-test feedback do not guide Coding.

File manifests and hashes detect input changes. Never mount the whole dataset into a candidate container. Material conflicts among authoritative requirements and tests require review; they are not automatically candidate failures.

See `../docs/EVALUATION_GUIDE.md` for the dataset fields and scoring workflow.
