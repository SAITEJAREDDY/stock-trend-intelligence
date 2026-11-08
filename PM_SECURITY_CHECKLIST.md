# PM Checklist: Security Architecture for an AI Agent

*What a product or program manager needs to know, what to write down, and what must be true before each gate opens.*

The [Security Roadmap](SECURITY_ROADMAP.md) explains *how* to secure an Azure Foundry agent. This page is the other half: how a PM keeps the work honest. You do not need to write the token-validation code. You do need to know which questions to ask, which documents must exist, and when to say "not yet."

Everything here is a practical suggestion, not a Microsoft requirement or a compliance standard. Adapt it to your organization's own policies. **Stock Trend Intelligence** is used as the running example.

## Part 1: Ten things a PM should understand

1. **An agent is a new kind of identity, not a feature.** It signs in, holds permissions and leaves an audit trail. Treat it like an employee account with a narrow job, not like a setting.
2. **Authentication and authorization are different.** Proving *who* the agent is does not decide *what* it may do. Both need an owner and a test.
3. **Least privilege is a scope decision you will be asked to approve.** A new agent identity starts with no permissions. Every role someone adds should be traceable to a named business need.
4. **Publishing can silently change the agent's identity.** In Foundry's publishing model, tool calls switch to the published application's identity and permissions do not carry over. Plan a post-publish permission check into every release.
5. **Public and unauthenticated is a decision, not a default.** It is acceptable for a read-only pilot on public data. It needs to be written down as an accepted risk with an expiry date.
6. **Tools are the blast radius.** An agent can only do what its tools allow. Count the tools, label each read-only or write-capable, and decide which need human approval.
7. **Data can leave your boundary.** Calls to non-Microsoft tools or data sources can send data outside Microsoft services. Someone must confirm that is allowed for the data involved.
8. **Third-party data has terms.** This project uses Yahoo Finance data through yfinance, which is unofficial and intended for personal or research use. A commercial product would need a licensed source.
9. **Preview features change.** Several Foundry identity and publishing features are in preview with no SLA. A roadmap that depends on them needs a fallback and a review date.
10. **If you cannot see it, you cannot defend it.** Logs, traces and alerts are part of the launch scope, not a follow-up ticket.

## Part 2: What to document (the evidence pack)

Keep these in one folder per agent. A gate review should be able to pass or fail from this pack alone.

| # | Document | What it must answer | Example from this project |
|---|---|---|---|
| 1 | **Agent card** | Purpose, owner, sponsor, users, data classification, tools, status | Stock-trend analysis; read-only; public market data |
| 2 | **Architecture and data-flow diagram** | Every hop, every identity, every trust boundary | [architecture.svg](docs/img/architecture.svg) |
| 3 | **Identity and permissions matrix** | Which identity holds which role, on what scope, and why | See the template below |
| 4 | **Tool inventory** | Each tool: read-only or write, approval mode, data touched | `get_stock_history`: read-only, auto-approved |
| 5 | **Threat and risk register** | Top risks, likelihood, impact, owner, mitigation, status | See the template below |
| 6 | **Test evidence** | Positive and negative tests with dates and results | No token, wrong audience and missing role are all rejected |
| 7 | **Data and legal notes** | Data sources, licences, retention, cross-border flows | Yahoo data via yfinance: personal and research use |
| 8 | **Runbook and rollback** | How to disable the agent, revoke access, rotate secrets | Delete the Render service; revoke the bot token in BotFather |
| 9 | **Monitoring plan** | Which logs, who reads them, which alerts page someone | Entra sign-in and audit logs, Foundry traces |
| 10 | **Cost guardrail** | Budget, alert threshold, kill switch | Free plan today; Azure cost analysis for Foundry |
| 11 | **Decision and exception log** | Every accepted risk, who accepted it, expiry date | Unauthenticated `/mcp` accepted for the pilot until Gate 3 |

### Template: identity and permissions matrix

| Identity | Type | Resource | Role or permission | Scope | Business reason | Approved by | Review date |
|---|---|---|---|---|---|---|---|
| Stock agent (dev) | Agent identity | MCP API | `Mcp.Invoke` | That API only | Call the one tool | | |
| Stock agent (published) | Agent identity | MCP API | `Mcp.Invoke` | That API only | Re-assigned after publish | | |
| Release engineer | User | Foundry account | Foundry Project Manager | Account | Publish the agent | | |
| App team | User or app | Agent Application | Foundry User | That application | Invoke the agent | | |

### Template: risk register

| ID | Risk | Likelihood | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| R1 | Anyone can call the public MCP endpoint and burn quota | High today | Medium | Entra token validation (Roadmap Phase 1) | Eng lead | Open |
| R2 | Published agent loses tool access after identity switch | Medium | Medium | Post-publish permission check | PM | Open |
| R3 | Prompt injection pushes the agent to misuse a tool | Medium | Low (read-only) | Guardrails, explicit approvals, read-only tools | Eng lead | Partly mitigated |
| R4 | Data source terms change or access is blocked | Medium | Medium | Alternative licensed provider identified | PM | Open |
| R5 | Preview feature changes break the design | Medium | Medium | Fallback plan, review each release | Eng lead | Open |

## Part 3: The gates

Each gate has a question, the evidence to attach, pass criteria and automatic blockers. A gate is passed only when a named approver signs it. "We will fix it after launch" is an exception, and exceptions need an owner and an expiry date.

### Gate 0: Intake (is this worth building?)

**Question:** do we understand what this agent is for and what it could touch?

- [ ] Agent card drafted with an owner and a sponsor
- [ ] Data classified (public, internal, confidential, regulated)
- [ ] List of intended tools and whether any can change or delete things
- [ ] Data sources and their licence terms identified

**Block if:** no named owner, or the data class is unknown.

### Gate 1: Design review (is the architecture sound?)

**Question:** does every hop have a named identity, and is the permission design least-privilege?

- [ ] Architecture and data-flow diagram reviewed
- [ ] Identity and permissions matrix filled in (even if provisional)
- [ ] Authentication method chosen for each tool connection (none, key, managed identity, agent identity, user OAuth)
- [ ] Unauthenticated endpoints, if any, recorded as accepted risks with an expiry date
- [ ] Threat and risk register started; top risks have owners
- [ ] Preview features listed, each with a fallback

**Block if:** a write-capable tool has no approval design, or an unauthenticated endpoint exposes anything beyond public data.

### Gate 2: Pre-production (does it behave under test?)

**Question:** do the controls actually work, including when someone attacks them?

- [ ] Positive test: authorized agent can call the tool
- [ ] Negative tests: no token, wrong audience, wrong tenant and missing role are rejected
- [ ] Guardrail and content-filter settings reviewed
- [ ] Tool approval mode set explicitly for every tool
- [ ] No secrets in the repository or its history (scan done and recorded)
- [ ] Logging and tracing turned on; a test event found in the logs
- [ ] Rate limits and a cost alert configured

**Block if:** any negative test passes when it should fail, or a secret is found in history.

### Gate 3: Go-live (are we ready to publish?)

**Question:** can we operate this, and can we shut it off?

- [ ] Permissions re-checked **after** publishing, on the published application's identity
- [ ] Callers hold only the role they need (for example Foundry User on the application)
- [ ] Runbook, rollback and kill switch tested once
- [ ] Alerts route to a named on-call person
- [ ] Exceptions from earlier gates are closed or re-approved with new expiry dates
- [ ] Hosting is appropriate for the trust boundary (not a free plan that sleeps and loses state, if availability or audit matters)
- [ ] Support and incident contacts published

**Block if:** the post-publish permission check was skipped, or nobody owns the alerts.

### Gate 4: Post-launch review (30 days in)

**Question:** is real usage matching the design?

- [ ] Review sign-in and audit logs for unexpected callers or roles
- [ ] Compare actual cost with the budget
- [ ] Review denied requests and guardrail hits
- [ ] Re-confirm every role assignment is still needed
- [ ] Update the risk register with what was learned

**Block if:** logs show callers or identities that were not in the matrix.

### Gate 5: Periodic review and retirement

**Question:** should this agent still exist, with these permissions?

- [ ] Quarterly: re-certify owners, sponsors and role assignments
- [ ] Each release: re-run negative tests and the post-publish permission check
- [ ] Each Foundry change that touches identity or publishing: re-read the docs and the roadmap
- [ ] Retirement: disable the agent, remove role assignments, revoke tokens, delete unused resources, archive the evidence pack

**Block if:** an owner has left and nobody has taken over.

## Part 4: Where Stock Trend Intelligence stands today

An honest read, using the gates above. It shows the checklist working, not a claim of production readiness.

| Gate | Likely outcome today | Why |
|---|---|---|
| 0 Intake | Pass | Purpose, owner and data class are clear: public market data, read-only |
| 1 Design review | Pass with exceptions | Unauthenticated `/mcp` must be logged as an accepted risk with an expiry date |
| 2 Pre-production | Not yet | No Entra token validation or negative tests exist (Roadmap Phase 1) |
| 3 Go-live | Not yet | Not published as an Agent Application; hosting is a free plan; alerts are not defined |
| 4 Post-launch | Not applicable | Wait until Gate 3 passes |
| 5 Periodic | Not applicable | Wait until Gate 3 passes |

That is a perfectly good place for a pilot to be, as long as everyone knows which gate it has passed.

## Part 5: Who signs what

| Role | Owns | Signs |
|---|---|---|
| **PM** | Evidence pack, gate scheduling, exception log, scope trade-offs | Gates 0 and 4 |
| **Engineering lead** | Identity design, token validation, tests, runbook | Gates 1 and 2 |
| **Security reviewer** | Threat model, negative-test results, guardrail settings | Gates 1, 2 and 3 |
| **Data or legal owner** | Data classification, licences, cross-border flows | Gate 0 and 3 |
| **Operations or on-call** | Alerts, kill switch, cost guardrail | Gate 3 |
| **Sponsor** | Accepting residual risk and exceptions | Gates 1 and 3 |

## Part 6: Red flags to escalate immediately

- A write-capable or destructive tool with approvals set to "never"
- Any agent using a shared identity with broad roles "just to get it working"
- Secrets in prompts, code, connection strings or repository history
- Tokens issued for a Microsoft audience being sent to your own server
- Launch scheduled before negative tests have been run
- Nobody can say who is paged when the agent misbehaves
- An exception with no expiry date
- A launch plan that depends on a preview feature with no fallback

## A one-page gate sign-off block

Copy this into each gate review.

```text
Agent:            ____________________
Gate:             ____________________
Date:             ____________________
Evidence pack:    ____________________ (link)
Result:           PASS / PASS WITH EXCEPTIONS / BLOCKED
Exceptions:       ID | description | owner | expiry date
Approver(s):      ____________________
Next review:      ____________________
```
