from .audit import write


class Tenures:
    """景区与运营方关系沿革：记录运营方任期，不产生任何材料使用授权。"""

    def __init__(self, connection):
        self.connection = connection

    def register_site(self, site_id, name, at, actor):
        if self.connection.execute("SELECT 1 FROM sites WHERE id=?", (site_id,)).fetchone():
            raise ValueError("景区已登记")
        with self.connection:
            self.connection.execute("INSERT INTO sites(id,name) VALUES(?,?)", (site_id, name))
            write(self.connection, at, actor, "site.register", site_id, {"name": name})

    def begin_tenure(self, tenure_id, site_id, operator, began_at, at, actor, note=""):
        if self.connection.execute("SELECT 1 FROM sites WHERE id=?", (site_id,)).fetchone() is None:
            raise KeyError(site_id)
        overlapping = self.connection.execute(
            "SELECT id FROM tenures WHERE site_id=? AND (ended_at IS NULL OR ended_at>=?) AND ?>=began_at",
            (site_id, began_at, began_at),
        ).fetchone()
        if overlapping:
            raise ValueError("该时段已有在任运营方")
        with self.connection:
            self.connection.execute(
                "INSERT INTO tenures(id,site_id,operator,began_at,note) VALUES(?,?,?,?,?)",
                (tenure_id, site_id, operator, began_at, note),
            )
            write(self.connection, at, actor, "tenure.begin", tenure_id,
                  {"site": site_id, "operator": operator, "began_at": began_at})

    def end_tenure(self, tenure_id, ended_at, at, actor):
        tenure = self.connection.execute("SELECT * FROM tenures WHERE id=?", (tenure_id,)).fetchone()
        if tenure is None:
            raise KeyError(tenure_id)
        if tenure["ended_at"] is not None or ended_at < tenure["began_at"]:
            raise ValueError("任期结束时间无效")
        with self.connection:
            self.connection.execute("UPDATE tenures SET ended_at=? WHERE id=?", (ended_at, tenure_id))
            write(self.connection, at, actor, "tenure.end", tenure_id,
                  {"site": tenure["site_id"], "operator": tenure["operator"], "ended_at": ended_at})

    def operator_at(self, site_id, at):
        row = self.connection.execute(
            "SELECT operator FROM tenures WHERE site_id=? AND began_at<=? "
            "AND (ended_at IS NULL OR ended_at>=?) ORDER BY began_at DESC LIMIT 1",
            (site_id, at, at),
        ).fetchone()
        return row["operator"] if row else None

    def lineage(self, site_id):
        rows = self.connection.execute(
            "SELECT id,operator,began_at,ended_at,note FROM tenures WHERE site_id=? ORDER BY began_at",
            (site_id,),
        ).fetchall()
        return [dict(row) for row in rows]
