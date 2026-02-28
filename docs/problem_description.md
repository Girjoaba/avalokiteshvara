# NovaBoard Hackathon 2026 - Team 1

## Build the *Production Scheduling* Agent

NovaBoard Electronics has 12 open orders, one production line, tight deadlines, and a conflict nobody has spotted yet. Your AI agent must read the factory state, detect the conflict, propose a schedule, and close the loop through the physical world.

### Mission Briefing (Team 1)

- **Tenant:** <https://hackathon1.arke.so/app>
- **Username:** `arke`
- **Password:** `arke`
- **Today:** Feb 28, 2026

---

## The Factory

Understand the world your agent lives in before building.

**February 28, 2026 - 08:00 AM**

You are the production planning manager at **NovaBoard Electronics**, a contract manufacturer that assembles printed circuit boards (PCBs) for industrial, medical, IoT, and agricultural customers. You do not sell products from a catalogue; you build what customers order, when they order it.

This morning you have **12 open sales orders** on your desk. Two customers need boards by Mar 3-4. **IndustrialCore** has a stopped production line and is losing money every hour. **MedTec Devices** has a late-delivery penalty clause. Earlier this morning, SmartHome IoT called: their product launch was moved up. They escalated **SO-005** (10x `IOT-200`) from P3 to P1.

What nobody has spotted yet: if SO-005 is blindly inserted into the P1 queue, **SO-003** (`AGR-400`, qty 5, deadline Mar 4) gets pushed one day late.

Your mission: build an AI agent that reads this situation, builds the production plan, detects the scheduling conflict, resolves it correctly, and keeps the operator in the loop through the physical world.

### Core Rules

#### Make to Order

You build what you sell. NovaBoard produces nothing speculatively. Every board is tied to a customer commitment:

- A **sales order** defines product, quantity, and delivery date.
- A **production order** is created in the factory to fulfill that commitment.

#### One Line, 7 Phases

Every product follows a fixed BOM phase sequence:

`SMT -> Reflow -> THT -> AOI -> Test -> Coating -> Pack`

All units in a batch move phase-by-phase together (batch sequential), and there is **one assembly line** (orders run one after another, never in parallel).

#### 480 min/day, 7 days/week

- Capacity: **8 hours/day = 480 min/day**
- Calendar: **7 days/week**
- Phase time formula: `duration_per_unit x quantity`
- Working days: `total_minutes / 480`

### The Four Decisions Your Agent Must Make

1. **What to produce?**  
   Read accepted sales orders. Decide one production order per sales order vs grouping by product. Grouping can reduce changeovers but forces earliest deadline across grouped lines.

2. **In what order?**  
   One line means sequential execution. Sort by urgency (deadline first; tie-breaker by priority where `1` is highest criticality).

3. **When does each department work?**  
   After creating a production order, call `_schedule` to generate phases, then assign concrete phase start/end dates using duration and 480 min/day constraints.

4. **What if priorities change?**  
   A customer escalates P3 -> P1. Agent must detect when strict priority causes deadline damage, compute a deadline-aware correction, notify operator, and update Arke after approval.

### Model Simplifications (for this challenge)

- **Single line:** real factories may run multiple lines; this challenge uses one.
- **Batch sequential:** no unit-level pipelining.
- **No per-department capacity model:** only line-level 480 min/day.
- **No changeover time:** setup switches are ignored.
- **7-day operation:** no weekend shutdown.

---

## Get Started

### 1) Add Arke MCP to your AI client

The MCP exposes API docs through `search_api`, so your agent can discover endpoints/schemas without guessing.

```bash
# Claude Code (one command)
claude mcp add arke --transport http https://arke.arkestaging.com/api/mcp-server/mcp
```

### 2) Explore your tenant

Your tenant is pre-loaded with orders, products, production phases, and warehouse data:

<https://hackathon1.arke.so/app>

### 3) Follow the challenge flow

Read orders -> choose policy -> create production orders -> schedule phases -> handle SmartHome priority conflict -> notify planner -> reschedule after approval.  
At least one step must be grounded in the physical world.

---

## MCP Setup

The MCP server is public (no auth required).  
Your agent authenticates to the **Arke API** (not MCP) using tenant credentials.

### Cursor

`~/.cursor/mcp.json`

```json
{"mcpServers":{"arke":{"url":"https://arke.arkestaging.com/api/mcp-server/mcp"}}}
```

### Windsurf

`~/.codeium/windsurf/mcp_config.json`

```json
{"mcpServers":{"arke":{"serverUrl":"https://arke.arkestaging.com/api/mcp-server/mcp"}}}
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{"mcpServers":{"arke":{"command":"npx","args":["-y","mcp-remote","https://arke.arkestaging.com/api/mcp-server/mcp"]}}}
```

### Replit

Tools -> Integrations -> MCP -> Add server

```text
Name: arke
URL:  https://arke.arkestaging.com/api/mcp-server/mcp
```

### API Auth Flow

Call:

`POST https://hackathon1.arke.so/api/login`

with:

```json
{"username":"arke","password":"arke"}
```

Use returned `accessToken` as:

`Authorization: Bearer <token>`

Token validity: 72 hours.

### Pre-generated Token (manual curl/Postman testing)

Valid until March 2 (if expired, call `/api/login` again).

```text
eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJlZTU0YTk4MS1mZTdhLTQwYTUtYWI2My0wZWZmMzY2MDQxZDUiLCJleHAiOjE3NzI0ODgwNTQsImlhdCI6MTc3MjIyODg1NCwiZnVsbF9uYW1lIjoiYXJrZSIsInVzZXJuYW1lIjoiYXJrZSIsInRlbmFudCI6eyJ0ZW5hbnRfaWQiOiIzYjFlYTQyNC0xODljLTQ5YzItYjU5Zi0yZTk4OWM0ZmVhYzEiLCJ0ZW5hbnRfdXJsIjoiaGFja2F0aG9uMSJ9LCJzdXBlcl9hZG1pbiI6ZmFsc2UsInJvbGVzIjpbImFkbWluIl19.fyJKQ37OUMXmxKqCqccAFxmKdly7XZ2749GK3m-eQA8IfMkYUMtiGKTT87YVDmNm_92Fs5ejNhE9VhekKMVmsBvFrlLLBOYXb0DOqbINjYU9ZQOny_L8RsJy0umMTHHEsMYwIK2qH4f5FrOzNYplM07Ny-WzPsjSJS9VMNIiXhmSk1jPWKzRXAe9eKmY1gRF7N78xpMvjq1YzEnQr0tiZfoKSsTky5WrcZmZecrGYX0po2zB_XVU1OHiAeFx2cle6Rpc2jEJXqj_i1TIuV51S7qx55U_l0TUuY4XtVWo6sTiaMkDvsjWPl2M-FkAn3R4w99pNP8n1vifNWKlS2Jepg
```

---

## The Challenge - 7 Steps

Build an AI agent that manages production end-to-end, with at least one step grounded in the physical world.

> **Planning vs Scheduling**
>
> - **Planning (Steps 2-3):** production-order level (`starts_at`/`ends_at`, batching policy).
> - **Scheduling (Step 4):** phase-level dates after `_schedule` expands BOM phases.

### Step 1 - Read open orders

Retrieve accepted sales orders and extract:

- product
- quantity
- deadline (`expected_shipping_time`)
- priority (`1` highest)
- customer

Show urgency-sorted summary.

APIs:

- `GET /api/sales/order?status=accepted`
- `GET /api/sales/order/_active`
- `GET /api/sales/order/{id}`

### Step 2 - Choose planning policy

No API needed (reasoning step).

**Level 1 (Required): Earliest Deadline First (EDF)**

- One production order per sales order line.
- Sort by nearest `expected_shipping_time`.
- Tie-break by priority (lower number wins).
- `ends_at` = corresponding sales order shipping date.

**Level 2 (Optional, higher score):**

- **Group by product:** merge lines of same product, sum quantity, set `ends_at` to earliest deadline in group.
- **Split in batches:** cap batch size (e.g., 10). Example: 20 units -> two batches of 10.

### Step 3 - Create production orders

Create production orders from Step 2 outcomes:

- `starts_at = today`
- `ends_at = deadline`

API:

- `PUT /api/product/production`

Example payload:

```json
{
  "product_id": "<id from GET /product>",
  "quantity": 20,
  "starts_at": "2026-02-28T08:00:00Z",
  "ends_at": "2026-03-02T17:00:00Z"
}
```

### Step 4 - Schedule phases

Call `_schedule` per production order (Arke builds phase sequence from BOM), then set phase dates sequentially.

Formula:

`total_minutes = duration_per_unit x quantity`

Working day: `480 min`.

APIs:

- `POST /production/{id}/_schedule`
- `GET /production/{id}`
- `POST /production-order-phase/{phaseId}/_update_starting_date`
- `POST /production-order-phase/{phaseId}/_update_ending_date`

### Step 5 - Human in the loop (planner approval)

Send proposed schedule via Telegram/Slack/Discord/etc.

Message must include:

- Full ordered schedule with start/end dates per production order.
- Explicit EDF reasoning for SO-005:
  - SO-003 (deadline Mar 4) should stay before SO-005 (deadline Mar 8), even if SO-005 is P1.

On approval:

- Move each production order to `in_progress` in Arke.
- First phase becomes `ready to start`.

If not approved:

- Adjust dates and re-present.

API:

- `POST /production/{id}/_confirm`

Tip: use `search_api("confirm production order")` in MCP to find exact endpoint details.

### Step 6 - Physical integration opportunity

Advance production using real signals.

Phase lifecycle:

`not_ready -> ready -> _start -> started -> _complete -> completed`

APIs:

- `POST /production-order-phase/{phaseId}/_start`
- `POST /production-order-phase/{phaseId}/_complete`

Examples:

- Camera validates phase completion before `_complete`.
- Defect detection pauses flow and notifies operator.
- Robot can move units/markers after phase completion.

### Step 7 - Re-plan / reschedule after feedback

Close the loop by handling planner modifications or runtime physical events (faults/defects) and then:

- recompute schedule (deadline-aware),
- update Arke dates/states,
- re-notify stakeholders with corrected plan.

---

## Physical Integration Layer

At least one step must be triggered or validated by a real sensor, camera, or actuator.

> **Core principle:** physical sensing must trigger a real Arke MCP action (not just logging). The signal must materially change production decisions.

### Option A (Recommended): Line Status Monitoring

Camera tracks line state (`running / idle / fault`). On fault, VLM reasoning triggers automatic re-scheduling via Arke MCP.

- Plugs into: Step 6
- Hardware: webcam + VLM

### Option B (Recommended): Phase Completion Verification

Camera confirms completion signal (e.g., green QC indicator) before calling `_complete`. Defects pause and notify.

- Plugs into: Step 6
- Hardware: webcam + VLM

### Option C (Bonus): Quality Gate with Actuation

Vision detects defects -> agent pauses phase in Arke -> LeRobot physically separates defective unit.

- Plugs into: Step 6
- Hardware: webcam + LeRobot

### Option D (Bonus): Physical Confirmation on Approval

Operator approves via messaging -> agent confirms in Arke -> LeRobot reorders physical priority markers/tokens.

- Plugs into: Steps 5-6
- Hardware: LeRobot

**Demo tip:** no real factory required. Printed status cards and colored tokens are enough if reasoning and decision impact are real.

---

## Your Factory Data

Pre-loaded in your tenant.  
Production phases: `SMT / Reflow / THT / AOI / Test / Coating / Pack`

### Products & BOM (minutes per unit)

| ID | Name | BOM - phases (min/unit each) | Total min/unit |
|---|---|---|---|
| `PCB-IND-100` | Industrial Control Board | SMT(30)->Reflow(15)->THT(45)->AOI(12)->Test(30)->Coating(9)->Pack(6) | 147 min |
| `MED-300` | Medical Monitor PCB | SMT(45)->Reflow(30)->THT(60)->AOI(30)->Test(90)->Coating(15)->Pack(9) | 279 min |
| `IOT-200` | IoT Sensor Board | SMT(18)->Reflow(12)->AOI(9)->Test(18)->Pack(6) | 63 min |
| `AGR-400` | AgriBot Control PCB | SMT(30)->Reflow(15)->THT(30)->AOI(12)->Test(45)->Coating(12) | 144 min |
| `PCB-PWR-500` | Power Management PCB | SMT(24)->Reflow(12)->AOI(9)->Test(24)->Pack(6) | 75 min |

### Sales Orders

| Order | Customer | Product | Qty | Deadline | Priority | Notes |
|---|---|---|---:|---|---|---|
| `SO-001` | IndustrialCore | `PCB-IND-100` | 2 | Mar 2 | P1 | URGENT - line stopped |
| `SO-002` | MedTec Devices | `MED-300` | 1 | Mar 3 | P1 | Penalty clause |
| `SO-003` | AgriBot Systems | `AGR-400` | 5 | Mar 4 | P2 | Spring deployment - confirmed window |
| `SO-004` | TechFlex | `PCB-IND-100` | 4 | Mar 6 | P2 |  |
| `SO-005` | SmartHome IoT | `IOT-200` | 10 | Mar 8 | P1 (escalated) | Priority escalated |
| `SO-006` | IndustrialCore | `PCB-PWR-500` | 8 | Mar 9 | P2 |  |
| `SO-007` | TechFlex | `IOT-200` | 12 | Mar 11 | P3 |  |
| `SO-008` | SmartHome IoT | `PCB-PWR-500` | 6 | Mar 12 | P3 |  |
| `SO-009` | MedTec Devices | `MED-300` | 3 | Mar 4 | P1 | Penalty clause |
| `SO-010` | IndustrialCore | `PCB-IND-100` | 8 | Mar 14 | P2 |  |
| `SO-011` | AgriBot Systems | `AGR-400` | 4 | Mar 13 | P3 |  |
| `SO-012` | TechFlex | `PCB-PWR-500` | 6 | Mar 15 | P4 |  |

### Capacity Reminder

One line, 480 min/day, 7 days/week, sequential batch processing.  
Phase time: `duration_per_unit x quantity`, then divide by 480 for working days.

### Critical Conflict to Detect

SO-005 was escalated P3 -> P1.  
A naive priority-first plan can schedule SO-005 before SO-003 and miss SO-003 by a day.  
An EDF-correct plan keeps SO-003 first (tighter deadline) and can still meet both.

---

## API Cheat Sheet

Use `search_api("your query")` in MCP for schemas.

| Method | Endpoint | Note |
|---|---|---|
| POST | `/api/login` | Get token with `{"username","password"}` |
| GET | `/api/sales/order` | List orders (`?status=accepted`) |
| GET | `/api/sales/order/_active` | Active orders shortcut |
| GET | `/api/product/product` | Products + BOM (`plan`) |
| GET | `/api/product/production-phase` | List production phases |
| GET | `/api/iam/warehouse` | List warehouses |
| PUT | `/api/product/production` | Create production order |
| POST | `/api/product/production/{id}/_schedule` | Generate phases from BOM |
| GET | `/api/product/production/{id}` | Production order + phases |
| POST | `/api/product/production-order-phase/{id}/_update_starting_date` | Set phase start |
| POST | `/api/product/production-order-phase/{id}/_update_ending_date` | Set phase end |
| POST | `/api/product/production-order-phase/{id}/_start` | Start phase |
| POST | `/api/product/production-order-phase/{id}/_complete` | Complete phase |
| POST | `/api/product/production/{id}/_update_starting_date` | Update production start |
| POST | `/api/product/production/{id}/_update_ending_date` | Update production end |

---

## Evaluation Criteria

| Area | Weight | What jury evaluates |
|---|---:|---|
| Functionality | 30% | End-to-end flow: read -> EDF -> create/schedule -> present -> approve -> execute |
| Policy Quality | 20% | Correct logic and date calculations across policies |
| Messaging Integration | 15% | Clear planner communication and action on approval/changes |
| Change Management | 15% | Correct handling of SO-005 escalation and SO-003/SO-005 conflict |
| UX & Presentation | 10% | Readable outputs (dashboard/Gantt/clarity) |
| Creativity & Bonus | 10% | Quality of physical loop, actuation, originality |

**What separates good from great:** physical sensing must genuinely change decisions. A useful camera-driven Arke action scores better than flashy but functionally irrelevant robotics.

---

NovaBoard Electronics Hackathon 2026 - <https://hackathon1.arke.so/app> - Team 1 - Good luck
