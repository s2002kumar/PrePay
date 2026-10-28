# ADR 0002: SFLLD source contract pinned to the Release 47 layout (covers Release 48)

- Status: accepted
- Date: 2026-10-28
- Scope: `src/prepay/contracts/sflld.py`, ingest (M1)

## Context

SPEC M1 asks for an official Release 47 schema adapter, plus a fallback for an earlier release
only if that release's layout is separately proven. It also forbids guessing file positions.
When this ADR was written, Freddie Mac had just published **Release 48** (2026-10-28,
origination and performance cutoff 2026-06-30). The blueprint was written against Release 47.

## Evidence (fetched 2026-10-28, SHA-256 pinned in `SOURCES`)

| Document | SHA-256 (prefix) | Finding |
|---|---|---|
| General User Guide, Release 48 (`user_guide.pdf`, same bytes as `general_user_guide_july_2026.pdf`) | `0884a958` | Field order and enumerations for both files |
| File Layout (`file_layout_july_2026.xlsx`, same bytes as `file_layout.xlsx`) | `e4ee4ba0` | Origination 31 fields, performance 35 fields, types, max lengths |
| File Headers (`file_headers_july_2026.zip`) | `db139053` | Official header text; matches our layout byte for byte |
| Disclosure Changes v1.2 | `e513ccc0` | Release 47 moved MI-cancellation and servicer name to performance, added VantageScore 4.0 and bankruptcy cramdown costs, re-coded delinquency (`00`/`01`/…/`RA`/`XX`) and payment deferral (`C`/`P`), flipped the sign of recoveries |
| Release Notes, Release 48 | `8c538246` | R48 = new data plus "minor bug fixes and data corrections"; no layout change |

These documents are part of the licensed dataset's documentation, so they are **not** committed.
The layout is encoded as code (positions, names, domains) with citations and a structural
fingerprint.

## Decision

1. One layout, `sflld-2026-07`, serves Releases 47 and 48. Every manifest records the release
   number and the layout fingerprint.
2. Releases 46 and earlier are **refused** with `UnsupportedReleaseError`. Their 32/32-field
   layout is mostly implied by the changes summary, but which of the two moved fields sat at
   origination positions 25 and 32 is not stated in any official artifact we hold. Freddie Mac
   distributes only the current release through Clarity, so the fallback adapter is
   **blocked** pending an official pre-R47 layout, not built on inference.
3. Value domains are strict. A value outside the documented enumeration or format is quarantined
   and counted, not coerced. Pre-R47 codings such as delinquency `0` and deferral `Y` therefore
   fail loudly. Bronze keeps raw strings, so nothing is lost.
4. Field count is strict. A row with any other number of fields fails the file. That includes a
   trailing delimiter, which the documents neither promise nor exclude. If real files show one,
   the contract gets a documented, tested update.
5. Release metadata (number, cutoffs) is declared by the researcher in `configs/data.lock.json`
   and cross-checked against `RELEASES`. Ingest never infers the release from the system date.

## Open questions to settle with downloaded files

- Do sample files end lines with a trailing `|`? (Unknown; strict width will surface it.)
- Does Net Sales Proceeds still use non-numeric markers (`C`/`U`) in Release 47+? The R48 guide
  documents only dollar amounts. Strict typing will surface any markers.
- Exact count of loans per partial 2026 vintage in the sample.

## Consequences

Ingest refuses any file that doesn't match the verified layout, so a researcher holding an
older release gets a clear error instead of silently misread columns.
