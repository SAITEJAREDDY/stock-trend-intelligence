# PM Field Notes: 7 Rules I'd Put on a Wall

Written after building Stock Trend Intelligence, not before. Each rule comes with the scar that taught it and the one question I would ask at a review. The longer, how-to version is the [Security Roadmap](SECURITY_ROADMAP.md).

## 1. Give the model conclusions, not raw data

**The scar:** I let the agent chew on multi-year price series and hit Azure token-rate errors. Raising the rate limit did not fix it. The fix was to do the math in Python and hand the agent a compact result plus chart links.

**The question:** *What is the biggest thing the model ever sees?* Less data in the prompt is cheaper, faster and leaves less for anyone to inject into or leak.

## 2. One tool, one verb, read-only

**The scar:** the playground failed because tool approvals were never supplied. I did not turn approvals off. I restricted the agent to a single tool, `get_stock_history`, and auto-approved only that one.

**The question:** *Can this tool change anything?* Name every tool and its approval mode. Read-only tools can be auto-approved. Anything that writes cannot.

## 3. The safest secret is the one you never create

**The scar:** the Alpha Vantage route needed a provider API key, so I did not finish it and used Yahoo data through yfinance instead. The only secret in the whole system is the Telegram bot token, and it lives in the host environment, not the repo. The trade-off is real: the data is unofficial and personal-use only.

**The question:** *How many secrets exist, who owns each, and how do I rotate it?* Then ask what you give up to avoid each one.

## 4. Not every path needs a model

**The scar:** the Telegram bot never calls an LLM. It parses a ticker, runs Python and sends back charts. No tokens spent, and no prompt for anyone to manipulate on that path.

**The question:** *Which requests really need the model?* The ones that do not are your cheapest and safest features.

## 5. Price the idle, not just the call

**The scar:** a Qwen option on an A100 was quoted at about $3.95 per hour *including idle time*. I never deployed it. Two cheaper models were deprecated or out of quota in my project anyway.

**The question:** *What does this cost while nobody is using it, and where is the kill switch?* Set a budget and an alert before deploying, not after the bill.

## 6. Write the "N/A" on purpose

**The scar:** one-week correlation shows N/A because five daily returns are not enough, and I would rather show nothing than a number that means nothing. Chart links expire after an hour. State resets on restart. All of it is written in the README.

**The question:** *What does this system refuse to say, and is that written down?* Honest limits stop users from over-trusting the output, and that is a security control.

## 7. Discussed is not built

**The scar:** I explored SMS through Twilio and created nothing: no account, no number, no billing. The notes say so, and the roadmap tracks Done and Gap in separate columns.

**The question:** *Is every item labelled done, planned or only discussed?* A plan that reads like a status report is how risks get approved by accident.

## The scar I expect next

I have not earned this one yet, so treat it as a prediction from the docs, not experience: **publishing an agent switches its tool calls to a new identity, and permissions do not carry over.** After the first publish I will check the MCP role on the new identity before I announce anything.

## The gate card

Six gates, one question each. If you cannot answer in one line with proof, the gate does not open.

| Gate | The one question | Proof I attach |
|---|---|---|
| 0 Intake | Who owns this, and what data does it touch? | Owner name and data class |
| 1 Design | What does the model see, and which tools can it use? | Diagram and tool list |
| 2 Pre-prod | What did I try to break, and what happened? | Negative tests: no token, wrong audience, missing role |
| 3 Go-live | Who gets paged, and how do I turn it off? | Named on-call and a tested kill switch |
| 4 After publish | What changed when the identity changed? | Role check on the published identity |
| 5 Retire | What am I switching off, and who confirms? | Roles removed, tokens revoked, resources deleted |

## Where this project is today

Past Gate 0. Gate 1 passes with one logged exception: the public, unauthenticated `/mcp` endpoint, accepted for a read-only pilot on public data. Gates 2 and 3 are not yet. The next work is Phase 1 of the roadmap: token validation on `/mcp` with negative tests.
