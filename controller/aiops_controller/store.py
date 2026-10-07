"""SQLite persistence: incidents (JSON document) and an append-only event timeline."""
import json, os, sqlite3, threading, time


class Store:
    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, created REAL, updated REAL, data TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT,
                                                  stage TEXT, summary TEXT, data TEXT);""")

    def save_incident(self, inc):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO incidents VALUES(?,?,?,?)",
                            (inc["id"], inc["created"], time.time(), json.dumps(inc)))
            self.db.commit()

    def incidents(self, limit=50):
        with self.lock:
            rows = self.db.execute("SELECT data FROM incidents ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_event(self, incident_id, stage, summary, data=None):
        ev = {"ts": time.time(), "incident_id": incident_id, "stage": stage, "summary": summary, "data": data or {}}
        with self.lock:
            cur = self.db.execute("INSERT INTO events(ts,incident_id,stage,summary,data) VALUES(?,?,?,?,?)",
                                  (ev["ts"], incident_id, stage, summary, json.dumps(ev["data"])))
            self.db.commit()
            ev["id"] = cur.lastrowid
        return ev

    def events(self, incident_id=None, limit=100):
        q, args = "SELECT id,ts,incident_id,stage,summary,data FROM events", []
        if incident_id:
            q, args = q + " WHERE incident_id=?", [incident_id]
        with self.lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()
        return [{"id": r[0], "ts": r[1], "incident_id": r[2], "stage": r[3], "summary": r[4], "data": json.loads(r[5])}
                for r in rows]
