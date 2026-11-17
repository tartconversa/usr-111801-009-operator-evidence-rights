from .gate import Gate, STATUS_ORDER
from .products import Products
from .tenure import Tenures


class Availability:
    """面向新运营团队的材料可见性视图。

    只返回元数据与可用状态，不返回原件正文；正文须经 Catalog.open_asset 关口。
    状态实时计算，因此许可撤销后清单会立即反映为不可用。
    """

    def __init__(self, connection):
        self.connection = connection
        self.gate = Gate(connection)
        self.tenures = Tenures(connection)
        self.products = Products(connection)

    def site_listing(self, site_id, recipient, purpose, at):
        operator = self.tenures.operator_at(site_id, at)
        rows = self.connection.execute(
            "SELECT a.id,a.source_id,a.digest,a.received_at,a.state,"
            "s.owner,s.jurisdiction,s.classification,s.active AS source_active "
            "FROM assets a JOIN sources s ON s.id=a.source_id "
            "WHERE s.site_id=? ORDER BY a.id",
            (site_id,),
        ).fetchall()
        items = []
        for row in rows:
            asset = dict(row)
            result = self.gate.evaluate(asset, recipient, purpose, at)
            items.append({
                "asset_id": asset["id"], "source_id": asset["source_id"], "owner": asset["owner"],
                "digest": asset["digest"], "received_at": asset["received_at"],
                "status": result["status"], "reasons": result["reasons"],
                "grant_id": result["grant_id"], "policy_revision": result["policy_revision"],
            })
        items.sort(key=lambda item: (STATUS_ORDER[item["status"]], item["asset_id"]))
        return {"site_id": site_id, "operator_at": operator,
                "recipient": recipient, "purpose": purpose, "at": at, "items": items}

    def check_references(self, product_id, revision, recipient, purpose, at):
        """复核引用校验：逐项给出引用原件对该领取方的实时可用状态。"""
        inputs = self.products.inputs(product_id, revision)
        if not inputs:
            raise KeyError((product_id, revision))
        items = []
        for asset in inputs:
            result = self.gate.evaluate(asset, recipient, purpose, at)
            items.append({
                "asset_id": asset["id"], "source_id": asset["source_id"], "owner": asset["owner"],
                "status": result["status"], "reasons": result["reasons"],
                "grant_id": result["grant_id"], "policy_revision": result["policy_revision"],
            })
        blocked = [item["asset_id"] for item in items if item["status"] != "available"]
        return {"product_id": product_id, "revision": revision,
                "recipient": recipient, "purpose": purpose, "at": at,
                "items": items, "blocked": blocked, "deliverable": not blocked}
