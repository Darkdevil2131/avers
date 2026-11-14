# Identify the running build

The workspace footer now contains **Build details** with the frontend revision
embedded during compilation and the backend revision returned by authenticated
`/session`. Different known revisions produce a mismatch warning. Missing or
invalid values display `unknown`, never a claim that the deployment is current.

Set `ARES_BUILD_REVISION` to the full 40-character Git commit SHA when building
the frontend and running the backend. For the supplied Dockerfile, use its
`ARES_BUILD_REVISION` build argument; it supplies both stages. For example, on
an already-authorized host and a clean checkout:

```bash
docker build --build-arg ARES_BUILD_REVISION="$(git rev-parse HEAD)" -t ares .
```

For separate frontend and API builds, pass the same SHA to `npm run build`
and to the API process environment. Do not label uncommitted files with a clean
commit's identity. These labels are operator-supplied diagnostic metadata, not
cryptographic attestation. Matching values alone do not prove latest-version,
worker, model or deployment health. Compare the displayed SHA with GitHub main
and the host's deployed commit. A runtime variable cannot relabel an already
compiled frontend: rebuild it.

The main HTML response now uses `Cache-Control: no-cache` so browsers revalidate
it; Vite's hashed asset names remain unchanged. This does not prove the user's
current stale page is caused by caching. Inspect the actual live URL and hosting
configuration before diagnosing or deploying. Existing builds must be updated
before this footer is available.

Validation: 103 backend tests passed (3 PostgreSQL tests require CI), 17 UI tests
passed, production build passed. Tests cover matching, mismatched, absent and
invalid revision labels and authenticated access. Browser acceptance and live
deployment remain unverified. No paid service, trial or hosting configuration
was changed.
