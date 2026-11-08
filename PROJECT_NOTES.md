# Project decisions and scope

## Goal

Enter one or more stock tickers and receive historical performance, return correlations and charts for 1D, 1W, 1M, 3M, 1Y and 3Y. Add a convenient messaging interface for a personal test.

## What was implemented

1. Cleaned the original Foundry instructions: removed copied setup prose and synthetic examples; removed repeated permission questions and promises of background work without tool execution.
2. Enabled Code Interpreter during the first implementation attempt and investigated historical market-data connections. An Alpha Vantage connection was not completed because it required a provider API key.
3. Built a Yahoo Finance/yfinance wrapper without a market-data provider key. Foundry's custom OpenAPI option was disabled in this UI, so the wrapper uses a Streamable HTTP MCP endpoint.
4. Created a private GitHub repository, containerized the service, and deployed it on Render's Free plan. Configured the /health check and GitHub-triggered deployments.
5. Connected the YahooStockHistory MCP tool to Foundry. Restricted the allowed tool and specific auto-approval list to get_stock_history, after the playground failed to supply required approvals.
6. Raw multi-year series triggered Azure token-rate errors. Attempting a higher deployment rate limit did not resolve the raw-series workflow. Moved numerical analysis and image generation into Python and replaced the prompt with compact-result instructions.
7. Removed Code Interpreter and web search from the agent. The tested Foundry path now calls the MCP service once in analysis mode, then explains compact results and links to charts.
8. Added a Telegram webhook, automatic registration from the Render environment token, ticker/alias commands, text replies, generated image uploads, duplicate-update checks, private-chat scope, throttling and a bounded worker queue.
9. Confirmed nine automated tests and live backend/Foundry/Telegram checks. See VALIDATION.md.

## Model choices

| Model | Outcome |
| --- | --- |
| GPT-5 mini | Already deployed; retained and successfully tested with compact results |
| GPT-4o mini | Investigated as a budget option; catalog marked it deprecated, and both Global Standard and Standard deployment attempts lacked quota in this project |
| GPT-5 nano | Investigated as another budget option; Global Standard deployment lacked quota |
| Qwen3.5-4B | Inspected a managed-compute option requiring an A100. UI estimated $3.95/hour including idle time; deployment was not submitted |

The Qwen estimate was a point-in-time quote, not a current price promise. No dedicated Qwen GPU was started. Telegram requests bypass the language model entirely and therefore do not consume Azure inference tokens through this implementation.

## Messaging alternatives considered

| Option | Decision |
| --- | --- |
| US SMS with Twilio | Discussed only; no Twilio account, number, registration, webhook or billing setup was created by this project |
| Personal mobile number | Can be a tester's number; verifying it does not make it a programmable Twilio SMS sender |
| Google Voice | Not chosen for scripted bot messaging |
| Telegram | Implemented; no separate bot phone-number rental or US SMS registration workflow |

Earlier SMS cost estimates depended on eligibility for a specific verification route and were not a quote for a confirmed setup. Review the provider's current requirements and checkout pricing before spending money. No SMS setup cost is part of the running Telegram implementation.

## Current boundaries

- Deterministic ticker/alias commands, not arbitrary natural-language conversations in Telegram.
- On-demand replies only; no automatic subscriptions, price alerts or scheduled messages.
- Personal/research pilot with in-memory state, not a durable production messaging platform.
- No actual-cost audit or project cleanup was performed.

## Possible future work

Add a durable job queue and deduplication store, stronger public-endpoint rate limiting, exchange-calendar-aware intraday sessions, on-demand chart selection, additional company-name resolution, FX-normalized comparisons and an available low-cost model only if natural-language interpretation is needed. These items are not implemented promises.
