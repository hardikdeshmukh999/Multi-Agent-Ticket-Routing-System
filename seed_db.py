"""
seed_db.py — Creates and seeds the support database with realistic Microsoft-style data.
Run once: python seed_db.py
"""

import sqlite3
import random
from faker import Faker

DB_PATH = "support.db"
fake = Faker()
random.seed(42)
Faker.seed(42)


DEPARTMENTS = [
    # (id, name, parent_id, level, sla_hours, escalation_dept_id)
    (1,  "Microsoft Support HQ",  None, 0, 72,  None),
    (2,  "Subscriptions",         1,    1, 24,  1),
    (3,  "Technical Support",     1,    1, 12,  1),
    (4,  "Licensing",             1,    1, 48,  1),
    (5,  "Security",              1,    1, 4,   1),
    (6,  "Billing",               2,    2, 24,  2),
    (7,  "Renewals",              2,    2, 48,  2),
    (8,  "Azure Support",         3,    2, 8,   3),
    (9,  "Microsoft 365 Support", 3,    2, 12,  3),
    (10, "Teams & Collaboration", 3,    2, 12,  3),
    (11, "Volume Licensing",      4,    2, 48,  4),
    (12, "OEM & Retail",          4,    2, 72,  4),
    (13, "MFA & Authentication",  5,    2, 4,   5),
    (14, "Breach Response",       5,    2, 1,   5),
]

AGENTS = [
    # (id, name, dept_id, level, max_tickets)
    (1,  "Sarah Chen",       6,  "L2", 8),
    (2,  "Marcus Rivera",    6,  "L2", 8),
    (3,  "Priya Patel",      7,  "L2", 6),
    (4,  "James O'Brien",    7,  "L2", 6),
    (5,  "Amira Hassan",     8,  "L2", 5),
    (6,  "Tom Kowalski",     8,  "L2", 5),
    (7,  "Lin Wei",          9,  "L2", 8),
    (8,  "Fatima Al-Rashid", 9,  "L2", 8),
    (9,  "Carlos Mendez",    10, "L2", 7),
    (10, "Aisha Johnson",    10, "L2", 7),
    (11, "David Park",       11, "L2", 6),
    (12, "Nina Volkov",      11, "L2", 6),
    (13, "Raj Sharma",       12, "L2", 8),
    (14, "Emma Fischer",     13, "L2", 4),
    (15, "Omar Khalil",      13, "L1", 4),
    (16, "Zoe Williams",     14, "L1", 3),
    (17, "Ben Nakamura",     14, "L1", 3),
    (18, "Maria Santos",     2,  "L1", 10),
    (19, "Jake Thompson",    3,  "L1", 10),
    (20, "Leila Moradi",     4,  "L1", 10),
]

# Fixed demo accounts — must match DEMO_ISSUES in app.py
DEMO_CUSTOMERS = [
    ("Alex Morgan",      "alex.morgan@contoso.com",      "Azure Enterprise Agreement", "US",   1200, "enterprise"),
    ("Lisa Park",        "lisa.park@fabrikam.com",       "Microsoft 365 Business Premium", "US", 800, "smb"),
    ("Northwind DevOps", "dev@northwind.io",             "Azure Pay-As-You-Go", "EU",  450, "smb"),
    ("Mark Jones",       "mark.jones@adventureworks.com","Microsoft 365 Business Standard", "US", 600, "smb"),
    ("Tailspin Procurement", "procurement@tailspin.com", "Volume License", "US",  900, "enterprise"),
]

PLANS = ["Free", "Microsoft 365 Personal", "Microsoft 365 Business Basic",
         "Microsoft 365 Business Standard", "Microsoft 365 Business Premium",
         "Azure Pay-As-You-Go", "Azure Enterprise Agreement", "Volume License"]

ISSUE_TEMPLATES = [
    # (issue_text, dept_id, priority)
    ("My Microsoft 365 subscription expired but I was still charged $99 this month.", 6, "high"),
    ("I cannot log into the Azure portal. MFA code from Authenticator is not working.", 13, "urgent"),
    ("Microsoft Teams crashes every time I try to share my screen on macOS Ventura.", 10, "medium"),
    ("We suspect our Azure tenant has been compromised. Seeing unknown sign-ins from overseas.", 14, "urgent"),
    ("Our volume license agreement renewal was denied. We have 500 seats expiring next week.", 11, "urgent"),
    ("I was double-charged for my Microsoft 365 Business Premium subscription in March.", 6, "high"),
    ("Azure VM in East US region has been showing 503 errors for the past 6 hours.", 8, "urgent"),
    ("SharePoint Online is not syncing files with OneDrive. Getting error code 0x8004de40.", 9, "medium"),
    ("We need to transfer our OEM license to a new device after our laptop was stolen.", 12, "medium"),
    ("Microsoft Outlook keeps asking for password repeatedly even after re-entering it.", 9, "low"),
    ("Our company needs to downgrade from Business Premium to Business Basic for 200 users.", 7, "medium"),
    ("Azure Kubernetes Service pods are failing health checks after the latest node update.", 8, "high"),
    ("Cannot install Microsoft 365 apps — says license is not assigned but admin confirms it is.", 9, "medium"),
    ("Billing portal is showing incorrect renewal date — says 2022 instead of 2025.", 6, "low"),
    ("MFA is locked out for our entire organization after admin account was compromised.", 13, "urgent"),
    ("Microsoft Defender flagged suspicious PowerShell script running on 12 machines.", 14, "urgent"),
    ("Need to add 50 more seats to our existing volume license agreement mid-term.", 11, "medium"),
    ("Azure Blob Storage billing jumped 400% this month with no change in our usage patterns.", 8, "high"),
    ("Teams live events feature is not available despite having the correct license.", 10, "medium"),
    ("We received a notice that our Microsoft 365 tenant will be deleted in 30 days.", 7, "high"),
    ("Exchange Online email delivery is delayed by 2-4 hours for all external recipients.", 9, "high"),
    ("Our OEM Windows 11 Pro key is showing as invalid after reinstalling the OS.", 12, "low"),
    ("Azure Active Directory sync is failing — on-premises users cannot authenticate.", 13, "high"),
    ("Suspicious OAuth app was granted admin consent to our tenant without our knowledge.", 14, "urgent"),
    ("Microsoft Intune device enrollment is failing for all new iOS devices.", 10, "medium"),
    ("We are being charged for a Microsoft 365 plan we cancelled 3 months ago.", 6, "high"),
    ("Azure SQL Database is running at 100% DTU — performance is degraded for all users.", 8, "high"),
    ("Our volume licensing portal shows 0 licenses remaining but we purchased 300.", 11, "high"),
    ("Microsoft Forms responses are not being saved — data loss concern for ongoing survey.", 9, "medium"),
    ("Cannot renew Microsoft 365 Family subscription — payment page keeps timing out.", 7, "medium"),
]

STATUSES = ["open", "open", "open", "in_progress", "in_progress", "resolved", "escalated"]


def create_schema(cur: sqlite3.Cursor) -> None:
    cur.executescript("""
        DROP TABLE IF EXISTS tickets;
        DROP TABLE IF EXISTS agents;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS departments;

        CREATE TABLE departments (
            id              INTEGER PRIMARY KEY,
            name            TEXT NOT NULL,
            parent_id       INTEGER REFERENCES departments(id),
            level           INTEGER NOT NULL,
            sla_hours       INTEGER NOT NULL,
            escalation_id   INTEGER REFERENCES departments(id)
        );

        CREATE TABLE customers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            email           TEXT UNIQUE NOT NULL,
            plan            TEXT NOT NULL,
            region          TEXT NOT NULL,
            account_age_days INTEGER NOT NULL,
            tier            TEXT NOT NULL CHECK(tier IN ('consumer','smb','enterprise'))
        );

        CREATE TABLE agents (
            id              INTEGER PRIMARY KEY,
            name            TEXT NOT NULL,
            dept_id         INTEGER NOT NULL REFERENCES departments(id),
            level           TEXT NOT NULL,
            max_tickets     INTEGER NOT NULL,
            active_tickets  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id     INTEGER NOT NULL REFERENCES customers(id),
            issue_text      TEXT NOT NULL,
            dept_id         INTEGER REFERENCES departments(id),
            priority        TEXT CHECK(priority IN ('low','medium','high','urgent')),
            status          TEXT NOT NULL DEFAULT 'open',
            assigned_agent_id INTEGER REFERENCES agents(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at     TEXT
        );
    """)


def seed_departments(cur: sqlite3.Cursor) -> None:
    cur.executemany(
        "INSERT INTO departments VALUES (?,?,?,?,?,?)",
        DEPARTMENTS
    )


def seed_agents(cur: sqlite3.Cursor) -> None:
    for agent in AGENTS:
        active = random.randint(0, agent[4] - 1)
        cur.execute(
            "INSERT INTO agents VALUES (?,?,?,?,?,?)",
            (*agent, active)
        )


def seed_demo_customers(cur: sqlite3.Cursor) -> list[int]:
    ids = []
    for row in DEMO_CUSTOMERS:
        cur.execute(
            """INSERT INTO customers (name, email, plan, region, account_age_days, tier)
               VALUES (?,?,?,?,?,?)""",
            row,
        )
        ids.append(cur.lastrowid)
    return ids


def seed_customers(cur: sqlite3.Cursor, n: int = 60) -> list[int]:
    ids = seed_demo_customers(cur)
    tiers = ["consumer"] * 30 + ["smb"] * 20 + ["enterprise"] * 10
    random.shuffle(tiers)
    for i in range(n):
        tier = tiers[i]
        if tier == "enterprise":
            plan = random.choice(["Azure Enterprise Agreement", "Volume License"])
        elif tier == "smb":
            plan = random.choice(PLANS[2:6])
        else:
            plan = random.choice(PLANS[:3])
        cur.execute(
            """INSERT INTO customers (name, email, plan, region, account_age_days, tier)
               VALUES (?,?,?,?,?,?)""",
            (
                fake.name(),
                fake.unique.email(),
                plan,
                random.choice(["US", "EU", "APAC", "LATAM", "MEA"]),
                random.randint(30, 2000),
                tier,
            )
        )
        ids.append(cur.lastrowid)
    return ids


def seed_tickets(cur: sqlite3.Cursor, customer_ids: list[int], n: int = 55) -> None:
    agent_rows = cur.execute("SELECT id, dept_id FROM agents").fetchall()
    agent_by_dept: dict[int, list[int]] = {}
    for aid, did in agent_rows:
        agent_by_dept.setdefault(did, []).append(aid)

    for i in range(n):
        template = ISSUE_TEMPLATES[i % len(ISSUE_TEMPLATES)]
        issue_text, dept_id, priority = template
        cid = random.choice(customer_ids)
        status = random.choice(STATUSES)

        # pick an agent from the right dept if available
        agents_in_dept = agent_by_dept.get(dept_id, [])
        agent_id = random.choice(agents_in_dept) if agents_in_dept and status != "open" else None

        resolved_at = fake.date_time_this_year().isoformat() if status == "resolved" else None
        created_at = fake.date_time_this_year().isoformat()

        cur.execute(
            """INSERT INTO tickets
               (customer_id, issue_text, dept_id, priority, status, assigned_agent_id, created_at, resolved_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (cid, issue_text, dept_id, priority, status, agent_id, created_at, resolved_at)
        )


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    create_schema(cur)
    seed_departments(cur)
    seed_agents(cur)
    customer_ids = seed_customers(cur)
    seed_tickets(cur, customer_ids)
    conn.commit()
    conn.close()

    print(f"OK Database created at {DB_PATH}")
    print(f"  Departments : {len(DEPARTMENTS)}")
    print(f"  Agents      : {len(AGENTS)}")
    print(f"  Customers   : {60 + len(DEMO_CUSTOMERS)} ({len(DEMO_CUSTOMERS)} demo)")
    print(f"  Tickets     : 55")


if __name__ == "__main__":
    main()
