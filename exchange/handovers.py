from .audit import write
from .tenure import Tenures


class Handovers:
    """经营权接手登记。

    接手回执仅证明运营关系在某时点交接，不携带任何材料使用权；
    新团队能否使用旧材料，仍以当时有效的许可与策略为准。
    """

    def __init__(self, connection):
        self.connection = connection
        self.tenures = Tenures(connection)

    def record(self, handover_id, site_id, predecessor, successor, occurred_at, receipt, at, actor, note=""):
        if self.connection.execute("SELECT 1 FROM handovers WHERE id=?", (handover_id,)).fetchone():
            raise ValueError("接手编号已登记")
        predecessor_tenure = self.connection.execute(
            "SELECT 1 FROM tenures WHERE site_id=? AND operator=? AND began_at<=? "
            "AND (ended_at IS NULL OR ended_at<=?)",
            (site_id, predecessor, occurred_at, occurred_at),
        ).fetchone()
        if predecessor_tenure is None:
            raise ValueError("移交方在该景区没有早于交接时点的运营任期")
        if predecessor == successor:
            raise ValueError("移交方与接收方不应相同")
        if self.tenures.operator_at(site_id, occurred_at) != successor:
            raise ValueError("接收方在该时点不是景区在任运营方")
        with self.connection:
            self.connection.execute(
                "INSERT INTO handovers(id,site_id,predecessor,successor,occurred_at,receipt,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (handover_id, site_id, predecessor, successor, occurred_at, receipt, note),
            )
            write(self.connection, at, actor, "handover.record", handover_id,
                  {"site": site_id, "predecessor": predecessor, "successor": successor,
                   "occurred_at": occurred_at, "receipt": receipt})

    def for_site(self, site_id):
        rows = self.connection.execute(
            "SELECT id,predecessor,successor,occurred_at,receipt,note FROM handovers "
            "WHERE site_id=? ORDER BY occurred_at",
            (site_id,),
        ).fetchall()
        return [dict(row) for row in rows]
