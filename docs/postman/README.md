# Postman: Cascadia proxy

Importable Postman files for hitting a Cascadia proxy without hand-rolling `curl`.

- **`cascadia-proxy.postman_collection.json`** — the requests (chat completion, streaming, `/policy`, `/config`).
- **`cascadia-dev.postman_environment.json`** — the `dev` environment (`baseUrl` + an empty `bearerToken` for you to fill in).

## One-time setup

1. In Postman: **Import** → drop in **both** JSON files in this folder.
2. Top-right environment selector → choose **`cascadia-dev`**.
3. Open the environment (the eye icon, or **Environments** in the sidebar) and paste your token into **`bearerToken`**.
   - Get it from Railway: **`cascadia-proxy` service → Variables → `CASCADIA_PROXY_BEARER_TOKEN`** (click to reveal).
   - The token is stored only in your local Postman environment — it is **not** committed here (the file ships with an empty value).
4. Open **Chat completion (cascade)** and hit **Send**.

`baseUrl` defaults to the dev proxy (`https://cascadia-proxy-dev.up.railway.app`). Point it at any other Cascadia proxy by editing the variable.

## Notes

- **Bearer auth is set at the collection level** (`Authorization: Bearer {{bearerToken}}`), so every `/v1/*` request inherits it. The `/policy` and `/config` requests override it to *no auth* — those endpoints are public by design.
- Send `/policy` first to confirm which cascade is live (models, thresholds, shadow rates) before sending paid `/v1` traffic.
- Each successful chat completion returns an **`x-cascadia-request-id`** response header — the same UUID you can trace in the dashboard's Activity view.
- **Streaming** (`stream: true`) and **tool-use** requests deliberately bypass cascade escalation; the streaming request is included so you can see that behavior.
