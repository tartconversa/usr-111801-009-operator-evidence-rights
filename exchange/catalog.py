import hashlib
import json

from .audit import write
from .gate import Gate


class Catalog:
    def __init__(self, connection):
        self.connection = connection
        self.gate = Gate(connection)

    def register(self, source_id, owner, jurisdiction, classification, fields, at, site_id=None):
        if not fields or len({field[0] for field in fields}) != len(fields):
            raise ValueError("来源字段缺失或重复")
        if site_id is not None and self.connection.execute(
            "SELECT 1 FROM sites WHERE id=?", (site_id,)
        ).fetchone() is None:
            raise KeyError(site_id)
        with self.connection:
            self.connection.execute(
                "INSERT INTO sources(id,owner,jurisdiction,classification,site_id) VALUES(?,?,?,?,?)",
                (source_id, owner, jurisdiction, classification, site_id),
            )
            self.connection.executemany(
                "INSERT INTO fields(source_id,name,meaning,kind,sensitive) VALUES(?,?,?,?,?)",
                [(source_id, name, meaning, kind, int(sensitive)) for name, meaning, kind, sensitive in fields],
            )
            write(self.connection, at, owner, "source.register", source_id,
                  {"jurisdiction": jurisdiction, "site": site_id})

    def ingest(self, asset_id, source_id, payload, at):
        source = self.connection.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if source is None or not source["active"]:
            raise ValueError("来源不可用")
        allowed = {row[0] for row in self.connection.execute("SELECT name FROM fields WHERE source_id=?", (source_id,))}
        if not isinstance(payload, dict) or not payload or set(payload) - allowed:
            raise ValueError("记录字段不符合来源目录")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT INTO assets(id,source_id,schema_version,payload,digest,received_at) VALUES(?,?,?,?,?,?)",
                (asset_id, source_id, source["schema_version"], canonical, digest, at),
            )
            write(self.connection, at, source["owner"], "asset.ingest", asset_id, {"source": source_id, "digest": digest})
        return digest

    def get(self, asset_id):
        row = self.connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return dict(row)

    def open_asset(self, asset_id, recipient, purpose, at):
        """领取方取原件：元数据始终可查，原件正文必须通过实时许可关口。

        许可撤销后，即便此前已出具接手/交付回执，再次取件仍会被拒绝，
        拒绝原因写入审计留痕。
        """
        asset = self.connection.execute(
            "SELECT a.*,s.owner,s.jurisdiction,s.classification,s.active AS source_active "
            "FROM assets a JOIN sources s ON s.id=a.source_id WHERE a.id=?",
            (asset_id,),
        ).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        result = self.gate.evaluate(dict(asset), recipient, purpose, at)
        if result["status"] != "available":
            with self.connection:
                write(self.connection, at, recipient, "asset.deny", asset_id,
                      {"purpose": purpose, "status": result["status"], "reasons": result["reasons"]})
            raise PermissionError(result)
        with self.connection:
            write(self.connection, at, recipient, "asset.open", asset_id,
                  {"purpose": purpose, "grant": result["grant_id"]})
        return dict(asset)
