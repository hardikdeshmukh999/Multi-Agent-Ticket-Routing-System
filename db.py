"""
db.py — Thin database access layer. All SQL lives here.
"""

import sqlite3
from typing import Any

DB_PATH = "support.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Customer ──────────────────────────────────────────────────────────────────

def get_customer_by_email(email: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE LOWER(email) = LOWER(?)", (email,)
        ).fetchone()
    return dict(row) if row else None


def get_customer_tickets(customer_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.issue_text, t.priority, t.status, t.created_at,
                      d.name as dept_name
               FROM tickets t
               LEFT JOIN departments d ON t.dept_id = d.id
               WHERE t.customer_id = ?
               ORDER BY t.created_at DESC LIMIT 5""",
            (customer_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Department ────────────────────────────────────────────────────────────────

def get_all_departments() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM departments ORDER BY level, id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_department_by_name(name: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM departments WHERE LOWER(name) LIKE LOWER(?)",
            (f"%{name}%",)
        ).fetchone()
    return dict(row) if row else None


# ── Agent ─────────────────────────────────────────────────────────────────────

def get_available_agent(dept_id: int) -> dict | None:
    """Return the agent in this dept with the most capacity (lowest load ratio)."""
    with _conn() as conn:
        row = conn.execute(
            """SELECT * FROM agents
               WHERE dept_id = ? AND active_tickets < max_tickets
               ORDER BY (CAST(active_tickets AS REAL) / max_tickets) ASC
               LIMIT 1""",
            (dept_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_agents() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT a.*, d.name as dept_name
               FROM agents a JOIN departments d ON a.dept_id = d.id
               ORDER BY d.name, a.name"""
        ).fetchall()
    return [dict(r) for r in rows]


# ── Ticket ────────────────────────────────────────────────────────────────────

def create_ticket(customer_id: int, issue_text: str, dept_id: int,
                  priority: str, agent_id: int | None) -> int:
    status = "in_progress" if agent_id else "open"
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO tickets
               (customer_id, issue_text, dept_id, priority, status, assigned_agent_id)
               VALUES (?,?,?,?,?,?)""",
            (customer_id, issue_text, dept_id, priority, status, agent_id)
        )
        ticket_id = cur.lastrowid
        if agent_id:
            conn.execute(
                "UPDATE agents SET active_tickets = active_tickets + 1 WHERE id = ?",
                (agent_id,)
            )
    return ticket_id


def get_all_tickets(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.issue_text, t.priority, t.status, t.created_at,
                      c.name as customer_name, c.plan,
                      d.name as dept_name,
                      a.name as agent_name
               FROM tickets t
               JOIN customers c ON t.customer_id = c.id
               LEFT JOIN departments d ON t.dept_id = d.id
               LEFT JOIN agents a ON t.assigned_agent_id = a.id
               ORDER BY t.created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_stats() -> dict[str, Any]:
    with _conn() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        open_     = conn.execute("SELECT COUNT(*) FROM tickets WHERE status='open'").fetchone()[0]
        in_prog   = conn.execute("SELECT COUNT(*) FROM tickets WHERE status='in_progress'").fetchone()[0]
        resolved  = conn.execute("SELECT COUNT(*) FROM tickets WHERE status='resolved'").fetchone()[0]
        escalated = conn.execute("SELECT COUNT(*) FROM tickets WHERE status='escalated'").fetchone()[0]
        urgent    = conn.execute("SELECT COUNT(*) FROM tickets WHERE priority='urgent'").fetchone()[0]

        by_dept = conn.execute(
            """SELECT d.name, COUNT(t.id) as count
               FROM tickets t JOIN departments d ON t.dept_id = d.id
               WHERE d.level = 2
               GROUP BY d.name ORDER BY count DESC"""
        ).fetchall()

        by_priority = conn.execute(
            """SELECT priority, COUNT(*) as count FROM tickets
               GROUP BY priority ORDER BY count DESC"""
        ).fetchall()

        agent_load = conn.execute(
            """SELECT a.name, a.active_tickets, a.max_tickets, d.name as dept
               FROM agents a JOIN departments d ON a.dept_id = d.id
               ORDER BY a.active_tickets DESC LIMIT 10"""
        ).fetchall()

    return {
        "total": total, "open": open_, "in_progress": in_prog,
        "resolved": resolved, "escalated": escalated, "urgent": urgent,
        "by_dept": [dict(r) for r in by_dept],
        "by_priority": [dict(r) for r in by_priority],
        "agent_load": [dict(r) for r in agent_load],
    }
