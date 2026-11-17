from .audit import write


class Grants:
    def __init__(self, connection):
        self.connection = connection

    def issue(self, grant_id, source_id, recipient, purpose, valid_until, at, asset_ids=None):
        """登记许可。

        asset_ids 为空时许可覆盖整个来源；给出具体原件版本时，许可只放行这些版本，
        即补签后仅相应版本可用，同来源下其余版本仍不可用。
        """
        source = self.connection.execute("SELECT owner FROM sources WHERE id=?", (source_id,)).fetchone()
        if source is None:
            raise KeyError(source_id)
        if self.connection.execute("SELECT 1 FROM grants WHERE id=?", (grant_id,)).fetchone():
            raise ValueError("许可编号已登记")
        asset_ids = list(dict.fromkeys(asset_ids or []))
        if asset_ids:
            placeholders = ",".join("?" for _ in asset_ids)
            scoped = self.connection.execute(
                "SELECT id FROM assets WHERE id IN (" + placeholders + ") AND source_id=? AND state='active'",
                [*asset_ids, source_id],
            ).fetchall()
            if len(scoped) != len(asset_ids):
                raise ValueError("许可范围包含不属于该来源或不可用的原件版本")
        with self.connection:
            self.connection.execute(
                "INSERT INTO grants(id,source_id,recipient,purpose,valid_until) VALUES(?,?,?,?,?)",
                (grant_id, source_id, recipient, purpose, valid_until),
            )
            self.connection.executemany(
                "INSERT INTO grant_scopes(grant_id,asset_id) VALUES(?,?)",
                [(grant_id, asset_id) for asset_id in asset_ids],
            )
            write(self.connection, at, source["owner"], "grant.issue", grant_id,
                  {"source": source_id, "recipient": recipient,
                   "scope": "source" if not asset_ids else "assets", "assets": asset_ids})

    def revoke(self, grant_id, at, actor):
        grant = self.connection.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
        if grant is None:
            raise KeyError(grant_id)
        if grant["status"] != "active":
            raise ValueError("许可已撤销")
        with self.connection:
            self.connection.execute(
                "UPDATE grants SET status='revoked', revoked_at=? WHERE id=?", (at, grant_id)
            )
            write(self.connection, at, actor, "grant.revoke", grant_id,
                  {"source": grant["source_id"], "recipient": grant["recipient"], "revoked_at": at})

    def permits(self, source_id, recipient, purpose, at, asset_id=None):
        """返回放行该原件的有效许可编号；无有效许可时返回 None。

        来源级许可放行该来源全部版本；带范围的许可仅当范围包含该原件版本时放行。
        撤销、过期或范围不匹配都不放行，且每次取件实时判断，不缓存历史结论。
        """
        rows = self.connection.execute(
            "SELECT g.id, COUNT(gs.asset_id) AS scoped FROM grants g "
            "LEFT JOIN grant_scopes gs ON gs.grant_id=g.id "
            "WHERE g.source_id=? AND g.recipient=? AND g.purpose=? "
            "AND g.status='active' AND g.valid_until>=? GROUP BY g.id",
            (source_id, recipient, purpose, at),
        ).fetchall()
        for row in rows:
            if row["scoped"] == 0:
                return row["id"]
            match = self.connection.execute(
                "SELECT 1 FROM grant_scopes WHERE grant_id=? AND asset_id=?",
                (row["id"], asset_id),
            ).fetchone()
            if match:
                return row["id"]
        return None
