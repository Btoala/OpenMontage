# Recovery dashboard

A standalone, read-only inventory viewer for production preservation. This directory adds no hooks to Backlot, production pipelines, media tools or publishing workflows.

## Run the synthetic example

Requires Node.js 22 or newer; no dependencies, credentials or network access.

```bash
node verify.mjs
node build.mjs --input inventory.example.json --output /tmp/recovery-example --projects "Example film,Example series"
```

Choose a new empty output directory. Open its `index.html` in a browser. Search and filter by project, episode, version, asset type and evidence; inspect record details and export the current results as JSON or CSV. The page never edits sources, migrates files, scans storage or calls providers. It has no upload/import interface.

## Production use

Keep real inventories outside the public repository. Supply an explicit project allowlist to the build command. Unknown fields are discarded; allowed fields are type-checked. A production inventory may contain private paths and retrieval references even after credentials and unrelated records are excluded. Review free text and links before deploying to an owner-private host. Do not push private input, generated HTML or exports to a public branch. The directory ignore rules allow only the eight reviewed source files, but a forced Git add can bypass ignore rules.

The output is buildless static HTML, JSON, CSV and a content-hash manifest. Use a separate private Sites source repository with `.openai/hosting.json` pointing to `dist`, place the reviewed output there, and verify sole-owner access before publication. Keep prior source commits/snapshots. Never relax Site access to work around deployment failure. A static build does not grant access to linked source files; their original service permissions remain in force.

## Evidence contract

The input schema is `inventory.schema.json`. The builder accepts the historical `checks_today` field as `performed_checks`, always shown alongside the record's `evidence_date`. Snapshot/review dates are separate from file verification dates. Byte hashes, decoding, still-image review, continuous viewing, audio signal measurement, subjective listening, and native-editor checks are different evidence. Preserve actual check descriptions; do not fill unknowns with passes.

Every row identifies its project/episode, filename or explicit unknown, versions, location and location basis, stable retrieval/evidence links, optional SHA-256, evidence basis/date, file-open/picture/audio checks, lineage and recovery options. A hash reported in a document stays reported until verified against the actual bytes. Git commit IDs belong in storage-version fields, never SHA-256 fields. Missing means unrecovered within the stated scope, not proven destroyed.

Record originals, composite mixes, review proxies and reconstructions distinctly. A mixed-track extraction needs the parent content hash and derivation method; it is never silently relabeled an original stem. Parent records cannot cross project boundaries. Multipart archive pieces remain distinct from a restored archive and a playable master.

JSON/CSV export uses fixed fields and the build-time project allowlist. URLs reject credentials, signed/token queries, fragments, unrelated hosts and unsafe schemes. Text is inserted with `textContent`; embedded JSON escapes HTML delimiters. CSV formula-leading cells are escaped. These controls do not guarantee that every sensitive statement in an allowed text field has been detected. No runtime network, local-storage or source-writing API is present.

The viewer is a dated snapshot, not automatic monitoring. Refresh by scoped reads, preserve historical claims and checks, build into a new empty output directory, validate, and publish only to the approved audience. Restore or migration actions require their own explicit authorization and separate tools; this viewer provides neither.

## Validation

`verify.mjs` exercises public synthetic data, filtered-export boundaries, embedded JSON, unsafe links, CSV injection, typed fields, cross-project lineage, derivative provenance, credential screening and preservation of nonempty output directories. It does not restore production files or validate their artistic quality. Browser testing is required for a deployed build and target-phone listening remains a distinct media check.
