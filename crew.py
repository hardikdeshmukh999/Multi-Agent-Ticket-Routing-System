"""
crew.py — CrewAI multi-agent support routing pipeline.

Six specialist agents, each with a single responsibility:
  1. IntakeSpecialist   — look up customer + fetch history
  2. IssueClassifier    — route to correct department
  3. PriorityAnalyst    — score urgency
  4. Dispatcher         — assign agent + save ticket
  5. CommunicationsAgent — draft customer reply
  6. EscalationReviewer — decide if senior escalation needed
"""

import json
import os
from typing import Type

from crewai import Agent, Crew, Process, Task
from crewai.tools import BaseTool
from crewai import LLM
from pydantic import BaseModel, Field

import db

# Haiku is cheap and fast; disable_strict_tools fixes Claude + CrewAI incompatibility
_LLM = LLM(
    model="anthropic/claude-haiku-4-5-20251001",
    temperature=0.2,
    extra_body={"disable_strict_tools": True},
)


# ── Tool schemas ──────────────────────────────────────────────────────────────

class EmailInput(BaseModel):
    email: str = Field(description="Customer email address")

class DeptInput(BaseModel):
    department_name: str = Field(
        description=(
            "Target sub-department name. One of: Billing, Renewals, "
            "Azure Support, Microsoft 365 Support, Teams & Collaboration, "
            "Volume Licensing, OEM & Retail, MFA & Authentication, Breach Response"
        )
    )
    confidence: int = Field(description="Classification confidence 0-100")

class DeptIdInput(BaseModel):
    dept_id: int = Field(description="Department ID to search for available agents")

class SaveTicketInput(BaseModel):
    customer_id: int = Field(description="Customer ID from DB lookup")
    issue_text: str  = Field(description="Original issue text")
    dept_id: int     = Field(description="Resolved department ID")
    priority: str    = Field(description="One of: low, medium, high, urgent")
    agent_id: int | None = Field(description="Assigned agent ID, or null if none available")


# ── Tools ─────────────────────────────────────────────────────────────────────

class LookupCustomerTool(BaseTool):
    name: str = "lookup_customer"
    description: str = "Look up a customer record by email. Returns customer details and last 5 tickets."
    args_schema: Type[BaseModel] = EmailInput

    def _run(self, email: str) -> str:
        customer = db.get_customer_by_email(email)
        if not customer:
            return json.dumps({"found": False, "message": "No customer found."})
        tickets = db.get_customer_tickets(customer["id"])
        return json.dumps({"found": True, "customer": customer, "recent_tickets": tickets})


class ClassifyIssueTool(BaseTool):
    name: str = "classify_issue"
    description: str = "Resolve a department name to its DB record (id, name, sla_hours)."
    args_schema: Type[BaseModel] = DeptInput

    def _run(self, department_name: str, confidence: int) -> str:
        dept = db.get_department_by_name(department_name)
        if not dept:
            dept = {"id": 3, "name": "Technical Support", "sla_hours": 12}
        return json.dumps({
            "dept_id":    dept["id"],
            "dept_name":  dept["name"],
            "sla_hours":  dept["sla_hours"],
            "confidence": confidence,
        })


class FindAgentTool(BaseTool):
    name: str = "find_best_agent"
    description: str = "Find the available agent in a department with the lowest workload."
    args_schema: Type[BaseModel] = DeptIdInput

    def _run(self, dept_id: int) -> str:
        agent = db.get_available_agent(dept_id)
        if not agent:
            return json.dumps({"found": False, "agent": None})
        return json.dumps({
            "found": True,
            "agent": {
                "id":             agent["id"],
                "name":           agent["name"],
                "active_tickets": agent["active_tickets"],
                "max_tickets":    agent["max_tickets"],
            },
        })


class SaveTicketTool(BaseTool):
    name: str = "save_ticket"
    description: str = "Persist a finalised ticket to the database."
    args_schema: Type[BaseModel] = SaveTicketInput

    def _run(self, customer_id: int, issue_text: str,
             dept_id: int, priority: str, agent_id: int | None) -> str:
        ticket_id = db.create_ticket(customer_id, issue_text, dept_id, priority, agent_id)
        return json.dumps({"ticket_id": ticket_id, "saved": True})


# Instantiate tools (reused across agents that need them)
lookup_tool    = LookupCustomerTool()
classify_tool  = ClassifyIssueTool()
find_agent_tool = FindAgentTool()
save_tool      = SaveTicketTool()


# ── Agents ────────────────────────────────────────────────────────────────────

def make_agents() -> dict[str, Agent]:
    base = dict(llm=_LLM, verbose=False)

    intake = Agent(
        role="Intake Specialist",
        goal="Retrieve the full customer record and support history for every incoming ticket.",
        backstory=(
            "You are Microsoft's first point of contact. Your job is to identify "
            "the customer, confirm their plan and tier, and surface any relevant "
            "prior tickets before handing off to the routing team."
        ),
        tools=[lookup_tool],
        **base,
    )

    classifier = Agent(
        role="Issue Classifier",
        goal="Determine the single most appropriate sub-department to handle this issue.",
        backstory=(
            "You are a senior Microsoft support triage specialist with deep knowledge "
            "of the department hierarchy. You read the customer context from the Intake "
            "Specialist and route every ticket to the correct L2 sub-department with a "
            "confidence score. Routing guide:\n"
            "- Billing disputes / double charges → Billing\n"
            "- Subscription renewals / cancellations → Renewals\n"
            "- Azure VMs, AKS, Blob, SQL → Azure Support\n"
            "- M365, SharePoint, OneDrive, Exchange → Microsoft 365 Support\n"
            "- Teams, live events → Teams & Collaboration\n"
            "- Volume license agreements → Volume Licensing\n"
            "- OEM / retail keys → OEM & Retail\n"
            "- MFA lockouts, Authenticator → MFA & Authentication\n"
            "- Breaches, compromised accounts → Breach Response"
        ),
        tools=[classify_tool],
        **base,
    )

    priority_analyst = Agent(
        role="Priority Analyst",
        goal="Assign a priority level that accurately reflects urgency and customer impact.",
        backstory=(
            "You are Microsoft's SLA enforcement specialist. You consider the issue "
            "severity, customer tier, account age, and prior escalations. Rules:\n"
            "- urgent: breaches, MFA lockouts, outages affecting many users, data loss\n"
            "- high:   billing errors, degraded service, expiring critical licenses\n"
            "- medium: feature issues, sync problems, individual user blocks\n"
            "- low:    cosmetic bugs, informational questions\n"
            "Enterprise customers get one tier bump when in doubt."
        ),
        tools=[],
        **base,
    )

    dispatcher = Agent(
        role="Dispatcher",
        goal="Assign the ticket to the best available agent and persist it to the database.",
        backstory=(
            "You are Microsoft's operations dispatcher. You receive the classified, "
            "prioritised ticket and find the agent in the correct department with the "
            "most remaining capacity. You then save the final ticket record."
        ),
        tools=[find_agent_tool, save_tool],
        **base,
    )

    comms = Agent(
        role="Communications Agent",
        goal="Draft a professional, personalised opening reply for the customer.",
        backstory=(
            "You are a senior Microsoft customer communications specialist. "
            "You write clear, empathetic replies that acknowledge the issue, "
            "name the assigned agent and department, state the SLA response time, "
            "and add an urgency note for urgent tickets. Keep it concise — 4-6 sentences."
        ),
        tools=[],
        **base,
    )

    escalation = Agent(
        role="Escalation Reviewer",
        goal="Decide whether this ticket requires immediate senior escalation.",
        backstory=(
            "You are Microsoft's escalation manager. You review the full routing "
            "decision and flag tickets for escalation when: confidence < 70%, "
            "priority is urgent, the customer is enterprise tier with an outage, "
            "or there is a security breach. Provide a one-sentence reason."
        ),
        tools=[],
        **base,
    )

    return {
        "intake":        intake,
        "classifier":    classifier,
        "priority":      priority_analyst,
        "dispatcher":    dispatcher,
        "comms":         comms,
        "escalation":    escalation,
    }


# ── Tasks ─────────────────────────────────────────────────────────────────────

def make_tasks(agents: dict[str, Agent], email: str, issue: str) -> list[Task]:

    t1 = Task(
        description=(
            f"Look up the customer with email '{email}'. "
            "Return their full profile (name, plan, tier, region, account age) "
            "and a summary of their last 5 tickets."
        ),
        expected_output=(
            "A JSON object with keys: found (bool), customer (dict), "
            "recent_tickets (list). Include all fields returned by the tool."
        ),
        agent=agents["intake"],
    )

    t2 = Task(
        description=(
            f"Issue description: '{issue}'\n\n"
            "Using the customer context from Task 1, classify this issue to the "
            "correct L2 sub-department. Call classify_issue with the department name "
            "and your confidence score (0-100)."
        ),
        expected_output=(
            "A JSON object with keys: dept_id, dept_name, sla_hours, confidence."
        ),
        agent=agents["classifier"],
        context=[t1],
    )

    t3 = Task(
        description=(
            "Using the customer profile from Task 1 and classification from Task 2, "
            "assign a priority: low / medium / high / urgent. "
            "Provide a one-sentence reasoning."
        ),
        expected_output=(
            "A JSON object with keys: priority (string), reasoning (string)."
        ),
        agent=agents["priority"],
        context=[t1, t2],
    )

    t4 = Task(
        description=(
            "Using dept_id from Task 2 and priority from Task 3:\n"
            "1. Call find_best_agent with the dept_id\n"
            "2. Call save_ticket with: customer_id (from Task 1), "
            f"issue_text='{issue}', dept_id, priority, agent_id (or null)\n"
            "Return everything as a structured summary."
        ),
        expected_output=(
            "A JSON object with keys: agent (dict or null), ticket_id (int), saved (bool)."
        ),
        agent=agents["dispatcher"],
        context=[t1, t2, t3],
    )

    t5 = Task(
        description=(
            "Draft a professional opening reply email to the customer. "
            "Use: customer name (Task 1), issue summary, dept_name (Task 2), "
            "agent name (Task 4, or 'our team'), priority (Task 3), sla_hours (Task 2). "
            "Do NOT use any tools — write the email directly."
        ),
        expected_output=(
            "The full text of the customer reply email, starting with 'Dear [Name],'."
        ),
        agent=agents["comms"],
        context=[t1, t2, t3, t4],
    )

    t6 = Task(
        description=(
            "Review the full routing decision across all previous tasks. "
            "Decide: should this ticket be escalated? "
            "Answer with escalate: true/false and a one-sentence reason. "
            "Do NOT use any tools."
        ),
        expected_output=(
            "A JSON object with keys: escalate (bool), reason (string)."
        ),
        agent=agents["escalation"],
        context=[t1, t2, t3, t4],
    )

    return [t1, t2, t3, t4, t5, t6]


# ── Public API ────────────────────────────────────────────────────────────────

class RoutingResult:
    """Structured result returned to the Gradio UI."""
    def __init__(self):
        self.customer: dict          = {}
        self.dept_name: str          = "Unknown"
        self.dept_id: int            = 0
        self.sla_hours: int          = 24
        self.confidence: int         = 0
        self.priority: str           = "medium"
        self.priority_reason: str    = ""
        self.agent: dict | None      = None
        self.ticket_id: int | None   = None
        self.draft_reply: str        = ""
        self.escalate: bool          = False
        self.escalate_reason: str    = ""
        self.raw_outputs: list[str]  = []


def _try_parse_json(text: str) -> dict:
    """Best-effort JSON extraction from a task output string."""
    try:
        return json.loads(text)
    except Exception:
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}


def run_crew(email: str, issue: str, on_agent_done=None) -> RoutingResult:
    """
    Run the full 6-agent crew and return a RoutingResult.
    on_agent_done(index, raw_output) fires after each task completes.
    """
    agents = make_agents()
    tasks  = make_tasks(agents, email, issue)
    _counter = [0]

    def _task_cb(task_output):
        if on_agent_done:
            raw = task_output.raw if hasattr(task_output, "raw") else str(task_output)
            on_agent_done(_counter[0], raw)
        _counter[0] += 1

    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
        task_callback=_task_cb,
    )

    crew_output = crew.kickoff()

    result = RoutingResult()

    # Collect raw text from each task output
    task_outputs = []
    for to in crew_output.tasks_output:
        raw = to.raw if hasattr(to, "raw") else str(to)
        task_outputs.append(raw)
        result.raw_outputs.append(raw)

    # Parse task 1 — customer
    if len(task_outputs) > 0:
        d = _try_parse_json(task_outputs[0])
        result.customer = d.get("customer", {})

    # Parse task 2 — classification
    if len(task_outputs) > 1:
        d = _try_parse_json(task_outputs[1])
        result.dept_name  = d.get("dept_name", "Unknown")
        result.dept_id    = d.get("dept_id", 0)
        result.sla_hours  = d.get("sla_hours", 24)
        result.confidence = d.get("confidence", 0)

    # Parse task 3 — priority
    if len(task_outputs) > 2:
        d = _try_parse_json(task_outputs[2])
        result.priority        = d.get("priority", "medium")
        result.priority_reason = d.get("reasoning", "")

    # Parse task 4 — dispatch
    if len(task_outputs) > 3:
        d = _try_parse_json(task_outputs[3])
        result.agent     = d.get("agent")
        result.ticket_id = d.get("ticket_id")

    # Task 5 — draft reply (plain text, not JSON)
    if len(task_outputs) > 4:
        result.draft_reply = task_outputs[4].strip()

    # Parse task 6 — escalation
    if len(task_outputs) > 5:
        d = _try_parse_json(task_outputs[5])
        result.escalate        = bool(d.get("escalate", False))
        result.escalate_reason = d.get("reason", "")

    return result