# Validation record

These are point-in-time validation results, not an availability guarantee.

## Automated checks

`python -m unittest -q`: **9 tests passed**.

| Test area | Evidence covered |
| --- | --- |
| Daily calculations | Known proportional series produces correlation 1; one-day return matches direct calculation |
| Insufficient history | Missing 3Y baseline yields unavailable 3Y performance and correlation |
| Request validation | Reject invalid ticker/interval/range arguments |
| CSV handling | Preserve exchange-local session dates; retain missing values; exclude invalid closes |
| Error handling | Retrieval failures return no fabricated prices or private exception text |
| MCP | Initialize, list tools, call get_stock_history using the HTTP protocol |
| Telegram parser | Company aliases, ticker commands, duplicate tickers and invalid input |
| Telegram webhook | Secret header required, duplicate updates do not requeue, per-chat throttle enforced |
| Telegram reply | Mocked delivery receives the calculated text and actual generated chart bytes |

Mocks test delivery behavior without sending external test messages. The automated tests do not prove all Yahoo adjustments, exchange calendars or carrier/network behavior.

## Live checks completed

- Yahoo retrieval succeeded for MSFT and NVDA over more than three years (765 daily observations each in the initial 2023-10-20 to 2026-11-07 exclusive test).
- NVDA 5-minute retrieval succeeded with 156 observations in the initial two-session test.
- Compact analysis for MSFT/NVDA returned real six-period statistics and five chart references, with a response of approximately 5.6 KB in the local test.
- The hosted MCP endpoint returned compact analysis successfully; all five hosted PNG URLs returned HTTP 200 with nonempty image data.
- The Foundry comparison completed using GPT-5 mini after compacting the workflow, with performance/correlation results and chart links. Earlier raw-history attempts exceeded the model token-rate limit.
- Telegram getMe and webhook registration succeeded. The public health endpoint reports the configured bot username without revealing the token.
- Live Telegram analyses completed without reported processing failures. The worker counts an analysis completed only after its text/photo API calls finish without an exception. This verifies API-level processing; the Telegram phone UI was not independently inspected. No deployment-specific usernames, addresses or usage counters are recorded here.

## Important limits

- GPT-4o mini and GPT-5 nano deployment attempts were blocked by insufficient project quota; they were not activated. Qwen was not deployed.
- Free Render cold starts and redeployments can delay or lose in-memory work. The counters also reset after restart.
- 1W correlation normally has fewer than ten daily returns and is intentionally N/A.
- Chart URLs are temporary. Telegram uploads image bytes directly, so delivered photos do not depend on the URL cache afterward.
- External charts may appear as links or literal Markdown in the Foundry playground; inline rendering is client-dependent.
- No SMS integration, trades, proactive alerts, scheduled reports, production load testing or billing audit has been completed.
