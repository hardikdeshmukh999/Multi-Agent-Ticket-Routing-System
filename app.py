"""
app.py — Gradio UI for the Microsoft Support Routing Agent (CrewAI edition).

Tabs:
  1. Submit Ticket  — streams live agent progress, shows final result
  2. Ticket Queue   — browse all tickets in the DB
  3. Agent Roster   — view agents and live workloads
  4. Analytics      — routing stats dashboard
"""

import time
import threading
import gradio as gr

import db
from crew import run_crew, RoutingResult

PRIORITY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}
STATUS_EMOJI   = {"open": "📬", "in_progress": "⚙️", "resolved": "✅", "escalated": "🚨"}

AGENT_LABELS = [
    ("🔍", "Intake Specialist",    "Lookup customer & history"),
    ("🗂️",  "Issue Classifier",    "Route to sub-department"),
    ("📊", "Priority Analyst",     "Score urgency"),
    ("📦", "Dispatcher",           "Assign agent & save ticket"),
    ("✉️",  "Communications Agent","Draft customer reply"),
    ("🚨", "Escalation Reviewer",  "Escalation decision"),
]

DEMO_ISSUES = [
    ("alex.morgan@contoso.com",
     "We suspect our Azure tenant has been compromised. Seeing unknown sign-ins from Russia and China over the past 24 hours."),
    ("lisa.park@fabrikam.com",
     "My Microsoft 365 Business Premium subscription expired but I was still charged $299 this month. Please refund."),
    ("dev@northwind.io",
     "Azure Kubernetes Service pods failing health checks after last night's node pool update. Production is down for 200+ users."),
    ("mark.jones@adventureworks.com",
     "Cannot log in — MFA Authenticator app is not generating codes after I got a new phone. Locked out of everything."),
    ("procurement@tailspin.com",
     "Our 500-seat volume license agreement renewal was denied. Licenses expire in 4 days. Urgent escalation needed."),
]


# ── Formatting helpers ────────────────────────────────────────────────────────

def _steps_md(done_map: dict[int, str], active: int) -> str:
    rows = []
    for i, (icon, role, desc) in enumerate(AGENT_LABELS):
        if i in done_map:
            rows.append(f"### {icon} Agent {i+1}: {role}\n_{desc}_\n\n{done_map[i].strip()}")
        elif i == active:
            rows.append(f"### {icon} Agent {i+1}: {role}\n_{desc}_\n\n🔄 Running…")
        else:
            rows.append(f"### {icon} Agent {i+1}: {role}\n_{desc}_\n\n⏳ Waiting…")
    return "\n\n---\n\n".join(rows)


def format_agent_steps(result: RoutingResult) -> str:
    done = {i: raw for i, raw in enumerate(result.raw_outputs)}
    return _steps_md(done, active=-1)


def format_result_card(result: RoutingResult) -> str:
    p_icon     = PRIORITY_EMOJI.get(result.priority, "")
    esc_line   = "🚨 **Escalated to senior team**" if result.escalate else "✅ Standard routing"
    agent_name = result.agent["name"] if result.agent else "Unassigned (queued)"
    cname      = result.customer.get("name", "Customer")
    plan       = result.customer.get("plan", "—")
    tier       = result.customer.get("tier", "—").upper()

    return f"""## Routing result — Ticket #{result.ticket_id or '?'}

| Field | Value |
|---|---|
| Customer | {cname} ({tier}) |
| Plan | {plan} |
| Department | {result.dept_name} |
| Confidence | {result.confidence}% |
| Priority | {p_icon} {result.priority.upper()} |
| Assigned agent | {agent_name} |
| SLA | {result.sla_hours} hours |
| Escalation | {"Yes 🚨" if result.escalate else "No"} |

**Priority reasoning:** {result.priority_reason}

**Escalation note:** {result.escalate_reason}

{esc_line}

---

### Customer reply drafted

{result.draft_reply}
"""


# ── Tab 1: streaming pipeline ─────────────────────────────────────────────────

def run_pipeline(email: str, issue: str):
    """
    Gradio generator — yields (steps_md, result_md, status) tuples
    so the UI updates live while the crew runs in a background thread.
    """
    if not email.strip() or not issue.strip():
        yield "⚠️ Please enter both an email and issue description.", "", "⚠️ Fill in both fields."
        return

    # Initial state — all agents waiting
    yield _steps_md({}, active=0), "_Crew starting…_", "⏳ Starting crew…"

    # Shared state updated by the background thread
    completed: list[tuple[int, str]] = []
    result_holder: list[RoutingResult] = []
    error_holder:  list[str]           = []

    def _on_agent_done(idx: int, raw: str) -> None:
        completed.append((idx, raw))

    def _run() -> None:
        try:
            r = run_crew(email.strip(), issue.strip(), on_agent_done=_on_agent_done)
            result_holder.append(r)
        except Exception as exc:
            error_holder.append(str(exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Poll every 2 s and push updates to the UI
    while thread.is_alive() or (not result_holder and not error_holder):
        time.sleep(2)
        if error_holder:
            break

        done_map = dict(completed)
        active   = len(done_map) if len(done_map) < len(AGENT_LABELS) else -1
        n        = len(done_map)
        yield (
            _steps_md(done_map, active),
            "_Running — results appear when all 6 agents finish…_",
            f"⏳ Agent {n}/{len(AGENT_LABELS)} complete…",
        )

    if error_holder:
        yield f"❌ Crew error:\n\n```\n{error_holder[0]}\n```", "", "❌ Failed."
        return

    result    = result_holder[0]
    steps_md  = format_agent_steps(result)
    result_md = format_result_card(result)
    status    = (
        f"✅ Ticket #{result.ticket_id} created — "
        f"{result.dept_name} · {result.priority.upper()}"
    )
    yield steps_md, result_md, status


def load_demo(idx: int):
    return DEMO_ISSUES[idx]


# ── Tab 2: Ticket Queue ───────────────────────────────────────────────────────

def build_ticket_table():
    return [
        [
            f"#{t['id']}",
            t["customer_name"],
            t["plan"],
            t["issue_text"][:70] + ("…" if len(t["issue_text"]) > 70 else ""),
            t["dept_name"] or "Unrouted",
            f"{PRIORITY_EMOJI.get(t['priority'], '')} {t['priority'] or '—'}",
            f"{STATUS_EMOJI.get(t['status'], '')} {t['status']}",
            t["agent_name"] or "—",
            t["created_at"][:10],
        ]
        for t in db.get_all_tickets(limit=100)
    ]

TICKET_HEADERS = ["ID", "Customer", "Plan", "Issue", "Department", "Priority", "Status", "Agent", "Created"]


# ── Tab 3: Agent Roster ───────────────────────────────────────────────────────

def build_agent_table():
    rows = []
    for a in db.get_all_agents():
        pct = int(a["active_tickets"] / a["max_tickets"] * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        rows.append([a["name"], a["dept_name"], a["level"],
                     f"{a['active_tickets']}/{a['max_tickets']}", f"{bar} {pct}%"])
    return rows

AGENT_HEADERS = ["Agent", "Department", "Level", "Tickets", "Workload"]


# ── Tab 4: Analytics ──────────────────────────────────────────────────────────

def build_analytics() -> str:
    s = db.get_stats()
    dept_rows  = "\n".join(f"| {r['name']} | {r['count']} |" for r in s["by_dept"])
    prio_rows  = "\n".join(
        f"| {PRIORITY_EMOJI.get(r['priority'], '')} {r['priority']} | {r['count']} |"
        for r in s["by_priority"]
    )
    agent_rows = "\n".join(
        f"| {r['name']} | {r['dept']} | {r['active_tickets']}/{r['max_tickets']} |"
        for r in s["agent_load"]
    )
    return f"""## 📊 Support Operations Dashboard

### Volume overview
| Metric | Count |
|---|---|
| Total tickets | {s['total']} |
| 📬 Open | {s['open']} |
| ⚙️ In progress | {s['in_progress']} |
| ✅ Resolved | {s['resolved']} |
| 🚨 Escalated | {s['escalated']} |
| 🔴 Urgent | {s['urgent']} |

---

### By department (L2)
| Department | Tickets |
|---|---|
{dept_rows}

---

### By priority
| Priority | Count |
|---|---|
{prio_rows}

---

### Top 10 agents by active load
| Agent | Department | Active / Max |
|---|---|---|
{agent_rows}
"""


# ── App layout ────────────────────────────────────────────────────────────────

def build_app() -> gr.Blocks:
    with gr.Blocks(title="Microsoft Support Routing Agent", theme=gr.themes.Default()) as app:

        gr.Markdown(
            "# 🤖 Microsoft Support Routing Agent\n"
            "**CrewAI** — 6 specialist agents · sequential pipeline · real SQLite database"
        )

        with gr.Tabs():

            # ── Submit Ticket ──────────────────────────────────────────────
            with gr.TabItem("📨 Submit Ticket"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### New ticket")
                        email_input = gr.Textbox(
                            label="Customer email",
                            placeholder="customer@company.com"
                        )
                        issue_input = gr.Textbox(
                            label="Issue description",
                            placeholder="Describe the problem in plain language…",
                            lines=5
                        )
                        with gr.Row():
                            submit_btn = gr.Button("▶ Run crew", variant="primary")
                            clear_btn  = gr.Button("Clear")

                        gr.Markdown("**Demo scenarios** — one click to load:")
                        for i, (_, issue) in enumerate(DEMO_ISSUES):
                            btn = gr.Button(issue[:50] + "…", size="sm")
                            btn.click(fn=lambda idx=i: load_demo(idx),
                                      outputs=[email_input, issue_input])

                        status_box = gr.Markdown("")

                    with gr.Column(scale=2):
                        with gr.Tabs():
                            with gr.TabItem("🤖 Agent steps"):
                                steps_out = gr.Markdown(
                                    "_Load a demo or submit a ticket to watch each agent work…_"
                                )
                            with gr.TabItem("📋 Final result"):
                                result_out = gr.Markdown(
                                    "_Routing result appears here after the crew finishes._"
                                )

                # Use streaming=True so the generator yields update the UI live
                submit_btn.click(
                    fn=run_pipeline,
                    inputs=[email_input, issue_input],
                    outputs=[steps_out, result_out, status_box],
                )
                clear_btn.click(
                    fn=lambda: ("", "", "", ""),
                    outputs=[email_input, issue_input, steps_out, result_out],
                )

            # ── Ticket Queue ───────────────────────────────────────────────
            with gr.TabItem("🎫 Ticket Queue"):
                refresh_t = gr.Button("🔄 Refresh", size="sm")
                ticket_tbl = gr.Dataframe(
                    value=build_ticket_table(),
                    headers=TICKET_HEADERS,
                    interactive=False,
                    wrap=True,
                )
                refresh_t.click(fn=build_ticket_table, outputs=ticket_tbl)

            # ── Agent Roster ───────────────────────────────────────────────
            with gr.TabItem("👥 Agent Roster"):
                refresh_a = gr.Button("🔄 Refresh", size="sm")
                agent_tbl = gr.Dataframe(
                    value=build_agent_table(),
                    headers=AGENT_HEADERS,
                    interactive=False,
                )
                refresh_a.click(fn=build_agent_table, outputs=agent_tbl)

            # ── Analytics ──────────────────────────────────────────────────
            with gr.TabItem("📊 Analytics"):
                refresh_s = gr.Button("🔄 Refresh", size="sm")
                analytics_out = gr.Markdown(build_analytics())
                refresh_s.click(fn=build_analytics, outputs=analytics_out)

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(share=False)