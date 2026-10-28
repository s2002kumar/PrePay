# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's **Report a vulnerability** button
(*Security* tab → *Advisories*). Please don't open a public issue for security problems.
This is a personal research project maintained on a best-effort basis; there is no SLA.

## Scope and design

- The public demo serves **fictional** portfolios and a **synthetic-trained** model only. It loads
  a demo bundle that must be marked synthetic and whose seal must verify (ADR 0005). It can't
  read raw data, the research warehouse or real-trained runs.
- Model artifacts are JSON or LightGBM text, never pickle, so loading them can't execute code.
- The API enforces strict schemas, a 32 KiB body limit, per-client rate limiting, CSP and related
  security headers, and same-origin serving with no CORS.
- Public CI uses only synthetic data, SHA-pinned actions, a read-only token and no secrets.
  CodeQL, Dependabot alerts and updates, secret scanning and push protection are enabled.
- `prepay publication-check` scans tracked files, Git history and build outputs for restricted
  data and credentials before anything is published.

If you find real mortgage records, credentials or licensed Freddie Mac material anywhere in this
repository or its published artifacts, please report it privately as above.
