# Security Policy

## Supported Versions

This project is under active development. Only the `main` branch receives
security fixes.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report privately via GitHub's private vulnerability reporting:

- Go to the **Security** tab of this repository
- Click **Report a vulnerability**

Alternatively, email the repository owner listed in `CODEOWNERS`.

### What to include

- A description of the issue and its impact
- Steps to reproduce (proof-of-concept where possible)
- Affected versions / commit SHAs
- Any suggested mitigation

### What to expect

- **Acknowledgement:** within 3 business days
- **Initial assessment:** within 7 business days
- **Fix timeline:** depends on severity; critical issues are prioritized
- We will credit reporters in the release notes unless anonymity is requested

## Scope

In scope: source code in this repository and the CI/CD pipelines under
`.github/workflows/`.

Out of scope: third-party dependencies (report upstream), social engineering,
physical attacks, and denial-of-service against shared infrastructure.

## Automated Scanning

Every push and pull request is scanned by:

- **Trivy** — dependencies, secrets, and misconfiguration
- **CodeQL** — semantic SAST for Python

The build gate blocks any finding at **Critical** or **High** severity from
reaching production.
