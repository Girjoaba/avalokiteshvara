# Avalokiteshvara — AI-Powered Production Scheduling Platform

> **Avalokiteshvara** (Sanskrit: "the one who perceives the sounds of the world") — a real-time, AI-augmented production scheduling system that listens to factory events, operator commands, and customer deadlines to orchestrate optimal manufacturing schedules.

Built for **NovaBoard Electronics** — a contract PCB manufacturer running 12 concurrent sales orders on a single production line with 7 manufacturing phases, tight deadlines, and priority conflicts that require both deterministic algorithms and AI reasoning to resolve.

## 🎥 Demo
https://github.com/user-attachments/assets/15eeaa39-b0eb-47b4-b7d1-ea36265cb1bc

---

## Architecture Overview

Avalokiteshvara follows a **modular, event-driven architecture** with clear separation between scheduling logic, external integrations, and the operator interface. Every component communicates through well-defined async interfaces, making the system extensible and independently testable.

![Architecture Diagram](docs/architecture_diagram.png)

### Design Principles

- **Hybrid Intelligence** — deterministic EDF algorithm guarantees provably optimal deadline adherence, while Gemini AI handles nuanced operator requests and conflict resolution
- **Human-in-the-Loop** — every schedule change requires operator approval via Telegram before execution
- **Event-Driven Factory Integration** — the factory floor pushes failure events in real time, triggering immediate re-planning
- **Single Source of Truth** — the Arke Manufacturing API is the authoritative store; the system reads, computes, writes back, and never caches stale state

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SYSTEMS                              │
│                                                                        │
│   ┌──────────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│   │ Arke Mfg. API    │  │ Gemini AI    │  │ Factory Floor          │  │
│   │ (REST/JWT)       │  │ (2.5-flash)  │  │ (Cameras / Sensors)   │  │
│   └────────┬─────────┘  └──────┬───────┘  └───────────┬────────────┘  │
│            │                   │                      │               │
└────────────┼───────────────────┼──────────────────────┼───────────────┘
             │                   │                      │
     CRUD orders/dates   structured JSON I/O    POST /factory/failure
             │                   │                      │
┌────────────┼───────────────────┼──────────────────────┼───────────────┐
│            ▼                   ▼                      ▼               │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                   AVALOKITESHVARA CORE                           │ │
│  │                                                                  │ │
│  │  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────┐  │ │
│  │  │  Telegram    │  │    Scheduler     │  │  Factory Event     │  │ │
│  │  │  Bot         │◄─┤  Orchestrator    ├──►  Server            │  │ │
│  │  │             │  │                  │  │  (aiohttp:8080)    │  │ │
│  │  └──────┬──────┘  └───────┬──────────┘  └────────────────────┘  │ │
│  │         │                 │                                      │ │
│  │         │     ┌───────────┼───────────┐                         │ │
│  │         │     ▼           ▼           ▼                         │ │
│  │         │  ┌────────┐ ┌────────┐ ┌──────────┐                  │ │
│  │         │  │  AI    │ │ Gantt  │ │  Shared  │                  │ │
│  │         │  │ Helper │ │ Engine │ │  Models  │                  │ │
│  │         │  └────────┘ └────────┘ └──────────┘                  │ │
│  └─────────┼────────────────────────────────────────────────────────┘ │
│            │                                                          │
│            ▼                                                          │
│  ┌──────────────────┐  ┌──────────────┐                              │
│  │ Email (SMTP)     │  │ Operator     │                              │
│  │ Delay Notices    │  │ (Planner)    │                              │
│  └──────────────────┘  └──────────────┘                              │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Core Modules

### `src/scheduler_logic/` — Deterministic Scheduling Engine

The computational heart of the system. Produces provably correct schedules using classical real-time scheduling theory.

| Module | Responsibility |
|---|---|
| `planning.py` | **EDF (Earliest Deadline First)** sort — orders ranked by deadline, tie-broken by priority |
| `scheduling.py` | Working-hours arithmetic (480 min/day, 08:00–16:00 shifts), phase date computation, Arke PO creation |
| `orchestrator.py` | Top-level pipeline: fetch API state → run EDF → create production orders → assign phase dates → generate Gantt |
| `gantt.py` | Dark-themed Gantt chart renderer (matplotlib) — shows phases, deadlines, slack, and a "now" marker |
| `constants.py` | BOM phase durations, shift config, client emails, phase display colors |

**EDF Algorithm**: for a single-machine sequential schedule, EDF minimises the maximum lateness — it is the optimal policy under the factory's constraints. The implementation correctly handles the SO-005/SO-003 priority conflict: a P1 order with a later deadline does not preempt a P2 order whose deadline is tighter.

### `src/ai_scheduler_helper/` — AI-Powered Replanning

When the operator provides free-text feedback ("prioritise IndustrialCore", "move SO-007 earlier"), the system engages **Gemini 2.5 Flash** as a reasoning layer:

1. The current schedule and all pending orders are serialised into a structured `AIScheduleInput` JSON
2. An EDF baseline timeline is computed and included so the AI understands current deadline violations
3. Gemini returns a structured `AIScheduleOutput` with reordered IDs, priority updates, conflict warnings, and a human-readable comment
4. The orchestrator applies AI-suggested priority changes to the Arke API, then re-runs the full EDF pipeline in the AI-suggested order

The AI never executes actions directly — it proposes, the deterministic engine computes, and the operator approves.

### `src/telegram_control/` — Operator Interface

A full-featured Telegram bot providing real-time manufacturing oversight:

| Component | Features |
|---|---|
| **Dashboard** | Live order counts, production status, deadline alerts, priority breakdown |
| **Sales Orders** | Browse, paginate, edit priority/quantity/notes, delete — all via inline keyboards |
| **Production Orders** | View phases with progress bars, timing, status; remove from queue |
| **Schedule Management** | View current schedule, request new schedule (EDF), accept/reject proposed schedule, comment & revise (AI-powered) |
| **Notifications** | Phase completion, order completion, quality failures, deadline-at-risk alerts, factory failure alerts |
| **Delay Emails** | One-click SMTP dispatch of professional HTML delay notifications to affected customers |
| **Simulation Clock** | Set simulated time and speed multiplier for demo/testing scenarios |
| **Gantt Charts** | Inline Gantt chart images sent as photos with every schedule view |

All navigation is button-driven (inline keyboards). Free-text input is only requested for specific edits or AI comments.

### `src/process_factory_events/` — Factory Integration Layer

An **aiohttp HTTP server** running alongside the Telegram bot on port 8080 (configurable via `FACTORY_SERVER_PORT`).

**Endpoint**: `POST /factory/failure`

| Accepts | Description |
|---|---|
| Multipart form: `image` field | Photo of the failure from a factory camera |
| Multipart form: `description` field (optional) | Text description of the fault |
| Raw body (fallback) | Image bytes with any content type |

**Processing flow**:

1. Receive the failure image from factory cameras/sensors
2. Query all tracked production orders to find the one currently executing (by status or time window)
3. Resolve the linked sales order via the SO↔PO mapping
4. Send a Telegram photo notification to all subscribed operators with:
   - Failure image
   - Production order and sales order details
   - Customer information
   - Two action buttons: **Cancel Order** and **Restart Order**
5. Return a JSON response confirming delivery

**Operator actions** (via Telegram inline buttons):

| Action | Behavior |
|---|---|
| **Cancel Order** | Deletes the sales order from Arke (removes demand), then triggers full schedule recalculation. The cancelled order will not appear in the new schedule. |
| **Restart Order** | Keeps the sales order intact, triggers full schedule recalculation. A fresh production order is created for the same demand, re-scheduled from the beginning. |

Both actions call `request_new_schedule()` which: wipes all existing production orders → re-fetches current sales orders → runs EDF → creates new POs with correct phase dates in Arke → generates a new Gantt chart → presents the new schedule for approval.

### `src/shared/models.py` — Domain Model

Shared dataclasses used across all modules:

```
SalesOrder ──► SalesOrderLine ──► Product
     │
     ▼
ScheduleEntry ──► ProductionOrder ──► ProductionPhase
     │
     ▼
Schedule (id, entries[], status, conflicts[], notes)
     │
     ▼
ScheduleResult (schedule, gantt_image bytes, text_summary)
```

AI-specific types: `AIScheduleInput`, `AIScheduleOutput`, `AIPriorityUpdate`

Notification types: `Notification`, `NotificationType` (7 variants including `FACTORY_FAILURE`)

### `src/real_time/` — Physical Integration

Supports real-time phase advancement through the factory pipeline. The `RobotAvalokiteshvara` class interfaces with the physical production line, signalling phase completion/failure to drive the Arke API lifecycle:

```
not_ready → ready → _start → started → _complete → completed
```

---

## Integration Points

Avalokiteshvara connects to **5 external systems** through well-defined interfaces:

### 1. Arke Manufacturing API (REST/JWT)

| Direction | Operations |
|---|---|
| **Read** | Sales orders, products, production orders, phase status |
| **Write** | Create/delete production orders, schedule phases, update start/end dates, confirm/complete orders and phases |
| **Auth** | JWT token with auto-refresh on 401 |

Implemented via `ArkeAPIClient` — an async `httpx`-based client with automatic re-authentication.

### 2. Gemini AI (Google GenAI)

- Model: `gemini-2.5-flash` (configurable via `GEMINI_MODEL` env var)
- I/O: Structured JSON with `response_mime_type="application/json"`
- Temperature: 0.1 (near-deterministic)
- Invoked via `asyncio.to_thread` to avoid blocking the event loop

### 3. Factory Floor (HTTP Webhook)

- Protocol: HTTP POST with multipart image upload
- Endpoint: `http://<host>:8080/factory/failure`
- Tunnelable via ngrok/localhost.run for remote factory integration
- Triggers real-time Telegram notifications with operator decision prompts

### 4. Email (SMTP)

- Sends HTML delay notification emails to customers when schedule has late orders
- Configurable via `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` environment variables
- Professional email template with per-customer order breakdown, delay amounts, and on-time reassurances

### 5. Telegram Bot API

- Long-polling via `python-telegram-bot` v20+
- Pickle persistence for session state across restarts
- Inline keyboards for all navigation (no command memorisation needed)
- Photo messages for Gantt charts and factory failure images

---

## Data Flow

### Schedule Generation (Happy Path)

```
Operator clicks "New Schedule"
        │
        ▼
┌─ request_new_schedule() ─────────────────────────────────────┐
│  1. Delete all tracked production orders from Arke           │
│  2. Fetch current sales orders from Arke API                 │
│  3. [If AI comment] Call Gemini for reorder suggestion        │
│  4. [If AI] Apply priority updates to Arke                   │
│  5. Sort by EDF (deadline, then priority)                    │
│  6. For each pending SO:                                     │
│     a. Create production order in Arke (PUT)                 │
│     b. Generate phases from BOM (_schedule)                  │
│     c. Compute phase start/end dates (working-hours math)    │
│     d. Write phase dates to Arke API                         │
│     e. Write PO start/end dates to Arke API                  │
│  7. Generate Gantt chart (matplotlib → PNG bytes)            │
│  8. Build text summary with on-time/late analysis            │
│  9. Return ScheduleResult to Telegram layer                  │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
Operator sees schedule + Gantt chart
        │
   [Accept] or [Reject] or [Comment & Revise]
        │
        ▼
Accept: confirm all POs in Arke → production begins
Reject: delete all POs → back to clean slate
Comment: re-run pipeline with AI reorder → new proposal
```

### Factory Failure Flow

```
Factory camera detects defect
        │
        ▼
POST /factory/failure (image + description)
        │
        ▼
Server identifies executing PO + linked SO
        │
        ▼
Telegram notification with image → all subscribers
        │
        ├─── [Cancel Order] ──► delete SO + reschedule all
        │
        └─── [Restart Order] ──► keep SO + reschedule all
                                        │
                                        ▼
                                New schedule + Gantt chart
                                presented for approval
```

---

## Factory Constraints

| Parameter | Value |
|---|---|
| Production lines | 1 (sequential) |
| Working hours | 08:00 – 16:00 (480 min/day) |
| Calendar | 7 days/week |
| Phase sequence | SMT → Reflow → THT → AOI → Test → Coating → Pack |
| Phase time | `duration_per_unit × quantity` |
| Batch processing | All units move phase-by-phase together |

### Products & BOM

| Product | Total min/unit | Phases |
|---|---:|---|
| PCB-IND-100 | 147 | SMT(30) → Reflow(15) → THT(45) → AOI(12) → Test(30) → Coating(9) → Pack(6) |
| MED-300 | 279 | SMT(45) → Reflow(30) → THT(60) → AOI(30) → Test(90) → Coating(15) → Pack(9) |
| IOT-200 | 63 | SMT(18) → Reflow(12) → AOI(9) → Test(18) → Pack(6) |
| AGR-400 | 144 | SMT(30) → Reflow(15) → THT(30) → AOI(12) → Test(45) → Coating(12) |
| PCB-PWR-500 | 75 | SMT(24) → Reflow(12) → AOI(9) → Test(24) → Pack(6) |

---

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
git clone <repo-url>
cd avalokiteshvara
uv sync
```

### Environment Variables

Create a `.env` file:

```env
TELEGRAM_API_KEY=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key

# Optional
FACTORY_SERVER_PORT=8080
GEMINI_MODEL=gemini-2.5-flash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com
```

### Running

```bash
uv run -m src.telegram_control
```

This starts **both**:
- The Telegram bot (long-polling)
- The Factory Event Server on port 8080

### Testing the Factory Endpoint

```bash
curl -X POST http://localhost:8080/factory/failure \
  -F "image=@failure_photo.jpg" \
  -F "description=Soldering defect detected on unit 3"
```

For remote access (e.g., from a factory on another network):

```bash
ssh -R 80:localhost:8080 localhost.run
# Gives you a public HTTPS URL like https://abc123.lhr.life
```

---

## Project Structure

```
avalokiteshvara/
├── src/
│   ├── scheduler_logic/          # Deterministic scheduling engine
│   │   ├── orchestrator.py       #   Top-level compute_schedule pipeline
│   │   ├── planning.py           #   EDF sort algorithm
│   │   ├── scheduling.py         #   Working-hours math, phase date assignment
│   │   ├── gantt.py              #   Gantt chart renderer (matplotlib)
│   │   └── constants.py          #   BOM data, shift config, client emails
│   │
│   ├── ai_scheduler_helper/      # AI-powered replanning
│   │   └── gemini_replanner.py   #   Gemini structured I/O, prompt, parser
│   │
│   ├── telegram_control/         # Operator interface
│   │   ├── bot.py                #   Application builder, concurrent startup
│   │   ├── api_client.py         #   Async Arke API client (httpx)
│   │   ├── notifications.py      #   Push alerts to subscribed chats
│   │   ├── formatters.py         #   HTML message builders
│   │   ├── keyboards.py          #   Inline keyboard layouts
│   │   ├── models.py             #   Re-exports + display constants
│   │   └── handlers/
│   │       ├── onboarding.py     #     /start, settings, sim clock
│   │       ├── menu.py           #     Main menu, dashboard
│   │       ├── sales_orders.py   #     SO CRUD operations
│   │       ├── production.py     #     PO list, detail, remove
│   │       ├── schedule.py       #     Schedule view/request/accept/reject/comment
│   │       └── factory.py        #     Factory failure cancel/restart handlers
│   │
│   ├── process_factory_events/   # Factory integration HTTP server
│   │   └── server.py             #   aiohttp POST endpoint for failure events
│   │
│   ├── shared/
│   │   └── models.py             #   Domain dataclasses shared across modules
│   │
│   └── real_time/                # Physical integration
│       ├── advance_pipleine.py   #   Phase-by-phase execution driver
│       └── robot.py              #   Robot/sensor interface
│
├── docs/
│   ├── architecture_diagram.png  # System architecture diagram
│   ├── problem_description.md    # Hackathon challenge specification
│   └── swagger.yaml              # Arke API OpenAPI spec
│
├── tests/
│   ├── test_gemini_api.py        # AI replanner tests
│   └── test_so005_conflict.py    # EDF conflict detection tests
│
├── pyproject.toml                # Dependencies (uv)
└── .env                          # Environment variables (not committed)
```

---

## Key Algorithms

### Earliest Deadline First (EDF)

```python
sorted(orders, key=lambda o: (o.deadline, o.priority))
```

For a single machine with sequential processing, EDF minimises maximum lateness — proven optimal by Jackson's Rule (1955). The tie-breaker on priority (lower = more urgent) ensures deterministic ordering when deadlines coincide.

### Working-Hours Arithmetic

Production time spans multiple 8-hour shifts. The `add_working_minutes()` function correctly rolls across day boundaries:

```
Day 1: 08:00 ──────────── 16:00
Day 2: 08:00 ──────────── 16:00
       └─ 600 min of work spans 1.25 working days ─┘
```

### AI-Deterministic Hybrid

The AI never produces the final schedule. Instead:

1. **AI proposes** a reordering of sales order IDs based on operator intent
2. **EDF engine executes** the reordered sequence through the deterministic pipeline
3. **Arke API reflects** the computed dates as the source of truth

This ensures that AI suggestions always result in physically valid, constraint-respecting schedules.

---

## License

MIT
