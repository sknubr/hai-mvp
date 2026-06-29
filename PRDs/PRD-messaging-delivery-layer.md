# PRD: Messaging & Delivery Layer (WhatsApp / SMS / App)

> Companion to `PRD-persona-loop-mvp.md` and `memory-model-design.md`. This doc specs **how a character's messages reach a human, and how a human's messages reach the character** — across multiple transports — with a strong bias toward the product's defining feature: **unprompted async initiation** ("the character texts you first").
>
> **Framing:** this is not a "WhatsApp integration." It's a **channel-agnostic messaging layer** with WhatsApp as the first external adapter. The core loop must never know which transport delivered a message.

---

## 1. The one thing this PRD must protect

The product's differentiator is a character who is **co-present in your world** — it reaches out unprompted, in the moment, about real things. That means **async initiation is a first-class, v1-essential capability**, not a notification afterthought.

Every design decision below is in service of: *the character can initiate contact at the right moment, and converse in a natural async/text-like way, regardless of transport.*

---

## 2. Critical dependency (flagged, not assumed)

**Async initiation requires a delivery surface that permits unprompted outbound messages. The product's home app is currently UNDECIDED — this is the critical-path dependency for v1.**

Async push is essential, but the surface that delivers it best (native app push) is not yet committed. The abstract layer (§4) is what de-risks this: it specs the *capability*, and lets surfaces be swapped. But the capability is only as good as the best available surface. See the capability matrix in §6 — **the app decision should be driven by this PRD, not made around it.**

| If the app decision is… | Async initiation in v1 is… |
|---|---|
| Native app (push) | Fully unrestricted ✅ — the ideal |
| PWA / web push | Mostly works ⚠️ — iOS web-push is limited/unreliable |
| No owned surface; WhatsApp only | **Severely constrained** ❌ — only inside 24h window (see §5) |

**Recommendation: commit to an owned push surface (native or PWA) as the home for initiation. Do not let WhatsApp be the only surface, or the core feature dies on policy.**

---

## 3. Channel recommendation & rationale

**v1 stack: App (home + async initiation) → WhatsApp (first external conversational adapter) → SMS & others later.**

The key split that makes the policy problem tractable:

- **Initiation lives on the owned surface (app push).** Unrestricted, in-the-moment, no template approval, no carrier filtering, no time window. This is where "texts you first" is *natively free*.
- **Depth conversation can live on WhatsApp**, because async/text-like chat is its native feel (serves differentiator #2). Window-aware routing (§5) decides when a reach-out may flow through WhatsApp vs. must fall back to app push.

**Why WhatsApp before SMS:** SMS adds 10DLC registration, carrier filtering, no rich media, no read state, and the *same* initiation-window constraints — for more compliance pain and a worse texting feel. WhatsApp matches the async/text vibe and dominates most non-US markets. SMS becomes a later adapter for US users who won't install an app and don't use WhatsApp.

**Geography:** launching in WhatsApp-dominant markets sidesteps US SMS 10DLC entirely and is *less* effort. US/SMS can follow.

---

## 4. Architecture: the abstract messaging layer

One internal interface; transports are adapters behind it. The loop/memory systems talk only to the layer.

```
   ┌──────────────────────────────────────────────┐
   │  Core loop + memory  (transport-agnostic)      │
   │  emits OutboundMessage / receives InboundMessage│
   └───────────────────────┬────────────────────────┘
                            │
                ┌───────────▼────────────┐
                │   Messaging Layer        │
                │  - identity resolution   │
                │  - channel routing (§5)  │
                │  - async-initiation engine│
                │  - delivery status        │
                └───┬───────┬───────┬──────┘
                    │       │       │
              ┌─────▼─┐ ┌───▼───┐ ┌─▼─────┐
              │App Push│ │WhatsApp│ │ SMS   │   ← adapters
              │adapter │ │adapter │ │adapter│     (add more later)
              └────────┘ └───────┘ └───────┘
```

**Adapter contract (each transport implements):**
- `send(message, recipient)` → delivery result
- `receive(webhook payload)` → normalized `InboundMessage`
- `capabilities()` → { can_initiate, initiation_window, rich_media, read_receipts, … }
- compliance hooks: opt-in state, STOP/unsubscribe

**Message model (normalized, transport-independent):**
```
Message
  id, persona_id, user_id
  direction        : inbound | outbound
  channel          : app | whatsapp | sms
  body, media[]
  initiated_by     : character | user        -- async initiation lives here
  intended_send_at : timestamp               -- from delay buckets (loop PRD §6)
  sent_at, delivered_at, read_at
  status           : queued | sent | delivered | read | failed | blocked_by_policy
```

`intended_send_at` connects to the existing async delay mechanic (loop PRD §6) — the character "decides" to reach out; the layer figures out *how* given each channel's constraints.

---

## 5. The async-initiation engine + window-aware routing

This is the heart of the layer. When the loop decides a character should reach out (an event worth sharing, a journal moment, a re-engagement nudge), it emits an outbound message with `initiated_by = character`. The layer routes it:

```
character wants to reach out
        │
        ▼
  Is there an owned push surface (app/PWA) the user has?
        │ yes → send via app push   ✅ (unrestricted, preferred for initiation)
        │ no  ▼
  Is the user within WhatsApp's 24h window? (last user msg < 24h ago)
        │ yes → send via WhatsApp freely
        │ no  ▼
  Pre-approved WhatsApp template available & appropriate?
        │ yes → send template (limited, may feel less natural)
        │ no  → hold / downgrade to a non-initiation surface, or wait for user to re-open window
```

**The WhatsApp constraint, stated plainly:** outside a 24-hour window from the user's last message, WhatsApp only permits **pre-approved template messages** — fundamentally at odds with "spontaneously texts you about Wimbledon." This is *the* reason initiation should live on an owned push surface, and why routing exists. The constraint becomes a routing rule, not a wall — **but only if an owned surface exists** (§2).

---

## 6. Capability matrix (what each surface can actually do)

| Capability | App push (native) | PWA / web push | WhatsApp | SMS (US) |
|---|---|---|---|---|
| Unprompted initiation, any time | ✅ | ⚠️ iOS limited | ❌ only in 24h window / templates | ❌ heavily constrained |
| Natural async text feel | ✅ | ✅ | ✅ (best fit) | ⚠️ basic |
| Rich media / read state | ✅ | ✅ | ✅ | ❌ |
| Setup / compliance overhead | app store | low | Business API approval, templates | 10DLC, carrier filtering |
| Global reach without app install | ❌ | ⚠️ | ✅ | ⚠️ US-centric |

**Reading of the matrix:** initiation wants an owned surface; reach + natural feel wants WhatsApp; SMS is a fallback for a specific US segment. No single transport does everything — which is exactly why the abstract layer (§4) is the right call rather than over-engineering.

---

## 7. Multi-human note (ties to evolution model)

A character talks to many humans (differentiator #4), but per the two-layer evolution model discussed: **global "core self"** + **per-relationship memory/dynamic**. The messaging layer must therefore key every message and conversation by **(persona_id, user_id)** so each relationship is an isolated thread with its own history and window state — even though they share one evolving core self. The layer does not merge conversations across users.

---

## 8. Compliance & consent (noted as risk, minimal for now)

Flagged, not specced in detail (per scope decision):

- **Opt-in / consent** required before any character-initiated outbound on WhatsApp/SMS.
- **STOP / unsubscribe** handling is mandatory on SMS and WhatsApp; must be a first-class adapter hook.
- **WhatsApp Business API** approval + template pre-approval is a lead-time dependency — start early.
- **SMS 10DLC** registration (US) is why SMS is deferred.
- **Risk:** the more "human" and unprompted the messaging, the more it can read as unsolicited/spam to platforms. Initiation policy must be designed with this in mind. → dedicated compliance pass before any non-app channel goes live.

---

## 9. Relationship to MCP / funnel (from prior discussion)

MCP/ChatGPT-plugin is an **acquisition funnel, not a home** — it's request-response inside someone else's window and *structurally cannot do async initiation*. It can deliver the chat slice to introduce a character, then convert the user to an owned channel (app push / WhatsApp) where async actually lives. The messaging layer treats MCP, if built, as just another inbound adapter with `can_initiate = false`. Own the state + async; rent the discovery.

---

## 10. Out of scope for v1

- Full social-feed network dynamics (loop PRD already defers; feed stays a reflection/journal surface).
- SMS as a primary channel (later adapter).
- Voice / calls.
- Deep compliance build-out (§8 is a flag, not a spec).
- The "relationship can languish / character cools if neglected" dynamic — **parked, high-value, revisit deliberately** (see roadmap note below).

---

## 11. Build sequencing

1. **Decide the home/push surface** (§2) — critical path; everything downstream depends on it.
2. Build the **abstract messaging layer + message model** (§4) — transport-agnostic, wired to the loop's outbound/inbound.
3. Build the **app-push adapter** first (the unrestricted initiation surface).
4. Build the **async-initiation engine + window-aware routing** (§5).
5. Build the **WhatsApp adapter** (Business API; start approval/template process early per §8).
6. Keyed-by-(persona, user) threading (§7).
7. Compliance pass (§8) before WhatsApp goes live; SMS adapter later.

---

## Roadmap note (don't lose this)

**"You can't take the relationship for granted."** A character that can cool, drift, or get preoccupied when neglected is potentially one of the most compelling dynamics in the product — it's what separates a relationship from a vending machine. **But the edge that cuts you:** a user who feels *punished or abandoned* by something they pay for is a churn/trust problem. Design dial for later: characters may cool / be preoccupied / feel a little distant (human, creates healthy tension), but should rarely hard-abandon and never in a way that reads as the app withholding paid value. Parked deliberately, not dropped.
