# Spending controls

Paid generation is disabled by default. Local renderers, local synthesis,
reviewed free stock providers, and verified asset-cache hits remain usable.
Every live paid `BaseTool.execute()` call requires its own reviewed quote and
single-use approval. This includes tools imported directly, newly registered
providers and inherited API implementations. Attribution to a project is not
required, so changing an output path cannot escape the allowance.

## Setup and scope

The authority is `.openmontage-spending/ledger.sqlite3`, with a separate identity
marker. It is installation-wide, shared by all projects/processes in this
checkout. Back up the entire directory; do not delete it to resolve a failure.
The legacy per-project `cost_log.json` and Backlot cost displays are reporting
artifacts, not authorization. Existing balances are not silently imported.

The owner first reviews outstanding provider jobs and prior charges, sets
`budget.total_usd` and `budget.max_action_usd` in `config.yaml`, and initializes
the ledger with the reviewed opening liability. `reserve_pct` reduces the usable
total. The checked-in zero limits authorize no paid work. There are no env
disable switches or wildcard approvals. Missing, invalid, non-cap or nonfinite
configuration blocks paid work. Limits are re-read before approval and execution.

```sh
python -m lib.spending_cli init --opening-spend 0 --evidence 'Reviewed account; no outstanding charges/jobs'
python -m lib.spending_cli status
```

Initialization requires an exact interactive confirmation, and refuses an
existing directory. A missing/corrupt database never creates a fresh allowance.
If there are existing charges or outstanding jobs, use their total as the opening
balance rather than zero. This is a cumulative allowance, not a calendar reset.

## Quote, review, approve, execute

Keep production inside the existing pipeline stages and approval checkpoints.
This CLI is a tool-level accounting interface, not a production orchestrator.
Save the intended provider-native inputs in a JSON file, including model,
duration/count, quality, references and output path. Then obtain a local quote:

```sh
python -m lib.spending_cli quote openai_tts request.json --maximum 0.10
python -m lib.spending_cli show QUOTE_ID
```

The quote reports tool/provider/model, known units, estimated USD, maximum USD,
request hash, evidence and a 15-minute expiry. It never executes a tool. A zero,
missing or quote-required price on a paid path is not treated as free. Supply
`--quoted-usd` and `--evidence` only when a current account-specific provider
quote is required. Ordinary estimator errors must be fixed; manual quotes do
not suppress them. A quote is not an approval and does not itself reserve money.

After the human reviews the exact request JSON and quote, approval requires
typing `APPROVE <id> <maximum to six decimals> USD` in an interactive terminal:

```sh
python -m lib.spending_cli approve QUOTE_ID --evidence 'Ben approved this exact request and maximum in the recorded review'
python -m lib.spending_cli execute openai_tts request.json --approval QUOTE_ID
```

Only `execute` can call the provider. The Python equivalent remains
`registry.get(name).execute({**inputs, '_spending_approval': quote_id})`.
The wrapper removes the approval field before provider execution. Selectors
carry that token through a context variable to the chosen provider. Quote the
**adapted provider request**; a different provider, model, adaptation, file
content, credential/endpoint environment, tool source or parameter requires a
new approval. An approval covers one tool invocation, never a whole tool or
an unlimited batch. Batches inside one invocation must be included in the
reviewed inputs and maximum. New provider invocations need separate approvals.

Use `Ledger.quote`/the quote CLI for offline estimates. Passing `dry_run=true`
to `.execute()` is not an approval exemption: some providers' dry-run branches
contact remote services, and a flag alone does not prove that a call is free.

## Interruptions and billing

An atomic SQLite `BEGIN IMMEDIATE` transaction consumes the approval and commits
the full reviewed maximum **before** entering the tool. Other processes see
that liability. Reusing the token cannot resubmit, even after a timeout, crash
or restart. Another approval for an identical in-flight request is blocked.

Exceptions, cancellation, failed results and absent/zero/invalid actual-cost
reports retain the reservation and require reconciliation. A process killed
before cleanup leaves a durable `reserved` entry. Known job IDs returned by
providers are retained when available. Unknown acceptance never means a refund.
After an ambiguous result, further paid work is blocked pending reconciliation.

Even successful results retain the reviewed maximum, because most adapters
report an estimate rather than a billing receipt. A higher reported actual cost
is recorded and freezes further paid work. Release unused funds only after
checking the provider's receipt/job status or confirmed non-acceptance:

```sh
python -m lib.spending_cli show QUOTE_ID
python -m lib.spending_cli reconcile QUOTE_ID --actual-usd 0.08 --evidence 'Provider receipt/job reference and verified final USD cost'
```

Reconciliation requires the exact interactive `RECONCILE` phrase. It does not
make the original token reusable. Never reconcile an active job as free or
resubmit while provider acceptance is unknown. Resume/poll-only operations are
not automatically exempted: inspect the provider's job using its dashboard or
read-only client, reconcile, then explicitly review any follow-up tool request.

## Coverage at the audited fork

Discovery at `fecb9a1e3cc23ef84de30b272059457a427f16f8` finds 164 tools:
95 API, 9 hybrid, 45 local and 15 local-GPU. Of the API tools, six are reviewed
free stock/search tools; the other **89** are guarded, including hosted image,
video, avatar, music, speech, realtime audio, transcription, MiniCut, fal,
Atlas/Replicate/LTX schema adapters and their inherited implementations.

- The legacy hybrid `image_gen` is guarded unless `provider='local'` is explicit.
- TTS/image/video/capture selectors delegate; the provider is charged once.
- Remote ComfyUI image/video/music servers require a quote and approval even
  though their tool metadata says local-GPU. Loopback endpoints remain local.
- Known shared submit helpers (Atlas, Kling, provider_jobs, MiniCut `--yes`,
  realtime sessions, HeyGen and Modal) reject calls outside an authorized tool.
- Standalone HyperFrames cloud TTS/music, Gemini graphics placement and BFL
  reference generation examples are blocked at their paid entry points. Use
  governed tools. Local HyperFrames/Kokoro/MusicGen and manual placement remain.
- OpenAI SDK submission retries are explicitly disabled in the older TTS,
  Sora and legacy image adapters; no gate-level automatic retry is added.

The free exceptions are explicit module/name pairs. A new API/hybrid tool is
paid by default; returning zero or naming itself a selector does not exempt it.

## Honest boundaries

This prevents unapproved submissions and over-allocation of reviewed maxima
through the audited repository paths. It is **not a provider billing firewall**.
An inaccurate price, vendor-side overage or an internal SDK retry outside the
audited adapters can exceed an estimate after submission; application code cannot
undo an accepted charge. Use conservative provider-backed maxima and provider
account caps for an absolute account-level ceiling. No live billing was tested.

The operator/agent must be trusted not to forge human approval evidence, edit
code/config/SQLite, change input files during submission, call private adapters
or SDKs directly, or launch independent shell commands/plugins with credentials.
The interactive CLI prevents accidental automatic approval; it does not
cryptographically authenticate a human against code running as the same user.
Separate checkouts/machines have separate ledgers. Existing provider credentials,
third-party CLIs, local proxies to paid services and cloud-GPU hosting fees are
outside this ledger's account-wide authority. Unbounded realtime usage requires
a provider-backed maximum; there is no fabricated per-session price.

## Offline validation

`tests/tools/test_spending_controls.py` exercises the real gate and database with
mock providers and the repository's network-blocking test fixture. It covers
approval, quote drift, file changes, invalid amounts, limits, concurrent use,
ledger failures, cancellation, a killed subprocess, selectors, a mocked OpenAI
transport, registry-wide API coverage and blocked standalone helpers.

```sh
OPENMONTAGE_ALLOW_NETWORK=0 python -m pytest tests/tools/test_spending_controls.py -q
```

Do not pass real credentials or enable live-provider tests to validate this change.

Existing adapter unit tests mock the authorization backend in `tests/conftest.py`
so their provider protocol assertions remain focused. The `spending_controls`
marker disables that fixture and uses the real SQLite authority; all new tests
of enforcement must use that marker. Live tests also retain the real gate.
