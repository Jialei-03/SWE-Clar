# Security Policy

## Reporting a vulnerability

Please do not report security vulnerabilities in public GitHub issues, discussions or pull requests.

Report them privately by email to **dingxianwang@upwork.com** and **jialeili@mail.ustc.edu.cn**. Include:

- a description of the vulnerability and its potential impact;
- the affected files, commands or versions;
- steps to reproduce, or a proof of concept.

We will acknowledge your report and keep you informed of our progress. Please give us reasonable time to address the issue before disclosing it publicly.

## Scope

SWE-Clar is a research benchmark. Relevant reports include:

- weaknesses in the harness or task environments that let evaluated code escape its container or access the host;
- exposure of credentials, personal data or non-public material in the repository;
- vulnerabilities in the repository's own tools and scripts.

Task workspaces intentionally contain incomplete or incorrect code for evaluation. Defects in that code are part of the benchmark and are not security vulnerabilities.

## Safe use

Evaluated models run generated code. Run evaluations only inside the provided Docker environments, on machines that hold no sensitive data, and keep API keys in environment variables rather than configuration files.
