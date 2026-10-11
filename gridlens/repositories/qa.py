from gridlens.db import Database


class QARepository:
    def __init__(self, db: Database):
        self.db = db

    def list_answers(self) -> list[dict]:
        with self.db.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM qa_records ORDER BY created_at DESC")]

    def list_gaps(self) -> list[dict]:
        with self.db.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM knowledge_gaps WHERE status='open' ORDER BY updated_at DESC"
                )
            ]
