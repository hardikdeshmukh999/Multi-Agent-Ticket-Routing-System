## The 6 Agents — Input → Process → Output

---

**1. 🔍 Intake Specialist**

Input:
- Customer email address (typed by user)

What it does:
- Finds who the customer is before anything else
- Pulls their name, plan, tier (consumer/SMB/enterprise), region, account age
- Fetches their last 5 tickets to spot repeat issues

Technical steps:
- Calls `lookup_customer(email)` tool → hits `customers` table in SQLite
- Joins with `tickets` table to fetch history
- Returns full customer dict to next agent via CrewAI `context`

Output:
```json
{
  "found": true,
  "customer": {
    "id": 12, "name": "Lisa Park", "email": "lisa.park@fabrikam.com",
    "plan": "M365 Business Premium", "tier": "smb",
    "region": "US", "account_age_days": 847
  },
  "recent_tickets": [ ...last 5 tickets... ]
}
```

---

**2. 🗂️ Issue Classifier**

Input:
- Issue text (typed by user)
- Customer context from Agent 1 (tier, plan)

What it does:
- Reads the issue in plain English and picks the right sub-department
- Gives a confidence score (0-100%)
- Knows all 9 specialist teams and when to use each

Technical steps:
- Calls `classify_issue(department_name, confidence)` tool
- Fuzzy-matches department name → queries `departments` table
- Returns `dept_id`, `dept_name`, `sla_hours` to downstream agents

Output:
```json
{
  "dept_id": 6,
  "dept_name": "Billing",
  "sla_hours": 24,
  "confidence": 92
}
```

---

**3. 📊 Priority Analyst**

Input:
- Customer tier + plan from Agent 1
- Department + issue type from Agent 2
- Original issue text

What it does:
- Decides how urgent the ticket is: low / medium / high / urgent
- Considers customer tier — enterprise gets bumped up automatically
- Writes one-sentence reasoning for the audit trail

Technical steps:
- No tool calls — pure LLM reasoning
- Uses customer context from Agent 1 + classification from Agent 2
- Output feeds Agent 4 (what priority to save) and Agent 5 (tone of reply)

Output:
```json
{
  "priority": "high",
  "reasoning": "Unauthorized charge after subscription expiry
                warrants rapid financial investigation."
}
```

---

**4. 📦 Dispatcher**

Input:
- `dept_id` from Agent 2
- `priority` from Agent 3
- `customer_id` + issue text from Agent 1

What it does:
- Finds the best available human agent in the right department
- Picks whoever has the most remaining capacity
- Saves the complete ticket to the database

Technical steps:
- Calls `find_best_agent(dept_id)` → queries `agents` table, sorts by `active_tickets / max_tickets` ratio
- Calls `save_ticket(customer_id, issue_text, dept_id, priority, agent_id)` → inserts row into `tickets` table
- Updates `agents.active_tickets` counter

Output:
```json
{
  "agent": {
    "id": 1, "name": "Sarah Chen",
    "active_tickets": 4, "max_tickets": 8
  },
  "ticket_id": 56,
  "saved": true
}
```

---

**5. ✉️ Communications Agent**

Input:
- Customer name from Agent 1
- Department + SLA hours from Agent 2
- Priority from Agent 3
- Assigned agent name from Agent 4

What it does:
- Writes the opening reply email to the customer
- Personalises it — uses their name, names the assigned agent, states the SLA
- Adds urgency language automatically for urgent tickets

Technical steps:
- No tool calls — pure LLM generation
- Has context from all 4 previous agents
- Output is a ready-to-send email string, shown in the result card

Output:
```
Dear Lisa,

Thank you for contacting Microsoft Support. We have received
your request regarding the unexpected $299 charge on your
expired subscription. Your case has been assigned to Sarah Chen
in our Billing team. You can expect a response within 24 hours.

Best regards,
Microsoft Support
```

---

**6. 🚨 Escalation Reviewer**

Input:
- Full picture from all 5 agents:
  confidence score, priority, customer tier, issue type, agent assigned

What it does:
- Final check before the ticket is closed out
- Decides: does a senior manager need to see this right now?
- Escalates if confidence was low, priority is urgent, or it's a security breach

Technical steps:
- No tool calls — pure LLM reasoning
- Returns `escalate: true/false` + one-sentence reason
- If `true`, ticket status in DB is marked `escalated` instead of `in_progress`

Output:
```json
{
  "escalate": false,
  "reason": "Standard billing dispute within agent authority.
             Straightforward refund path, no senior review needed."
}
```

---

**Full data flow**

```
USER INPUT
email + issue text
      │
      ▼
Agent 1 ──► customer profile + history
      │
      ▼
Agent 2 ──► dept_id + dept_name + sla_hours + confidence
      │
      ▼
Agent 3 ──► priority + reasoning
      │
      ▼
Agent 4 ──► agent assigned + ticket saved to DB (ticket_id)
      │
      ├──► Agent 5 ──► draft reply email (shown to user)
      │
      └──► Agent 6 ──► escalate true/false + reason
```

Every agent receives ALL previous agents' outputs as context — Agent 6 sees everything Agent 1 through 5 produced. Nothing is passed in isolation.
