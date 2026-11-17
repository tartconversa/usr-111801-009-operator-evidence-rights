import hashlib
import json

from .audit import write
from .gate import Gate
from .products import Products
from .tenure import Tenures


class Delivery:
    def __init__(self, connection):
        self.connection = connection
        self.gate = Gate(connection)
        self.products = Products(connection)
        self.tenures = Tenures(connection)

    def send(self, delivery_id, product_id, revision, recipient, purpose, at):
        existing = self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if existing:
            if (existing["product_id"], existing["product_revision"], existing["recipient"], existing["purpose"]) != (product_id, revision, recipient, purpose):
                raise ValueError("交付编号已用于其他请求")
            return dict(existing)
        product = self.connection.execute(
            "SELECT state,site_id FROM products WHERE id=? AND revision=?", (product_id, revision)
        ).fetchone()
        if product is None or product["state"] != "draft":
            raise ValueError("数据产品修订不可交付")
        inputs = self.products.inputs(product_id, revision)
        if not inputs:
            raise ValueError("数据产品缺少输入")
        reasons, revisions, grant_evidence = [], {}, []
        for asset in inputs:
            source_id = asset["source_id"]
            result = self.gate.evaluate(asset, recipient, purpose, at)
            revisions[source_id] = result["policy_revision"]
            if result["status"] != "available":
                reasons.append({"source": source_id, "asset": asset["id"],
                                "status": result["status"], "reasons": result["reasons"]})
                continue
            grant_evidence.append({
                "asset_id": asset["id"], "source_id": source_id, "owner": asset["owner"],
                "grant_id": result["grant_id"], "policy_revision": result["policy_revision"],
            })
        if reasons:
            with self.connection:
                write(self.connection, at, recipient, "delivery.reject", product_id,
                      {"revision": revision, "reasons": reasons})
            raise PermissionError(reasons)
        # 快照交付时点的在任运营方：旧结论保留当时的运营方与许可依据，
        # 此后经营权再变更或许可撤销都不改动这条历史回执。
        operator = self.tenures.operator_at(product["site_id"], at) if product["site_id"] else None
        digest = hashlib.sha256("|".join(asset["digest"] for asset in inputs).encode()).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT INTO deliveries(id,product_id,product_revision,recipient,purpose,created_at,"
                "input_digest,policy_revisions,operator_at_delivery,grant_evidence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (delivery_id, product_id, revision, recipient, purpose, at, digest,
                 json.dumps(revisions, sort_keys=True), operator or "",
                 json.dumps(grant_evidence, ensure_ascii=False, sort_keys=True)),
            )
            write(self.connection, at, recipient, "delivery.accept", delivery_id,
                  {"product": product_id, "revision": revision, "operator": operator,
                   "inputs": [a["id"] for a in inputs]})
        return dict(self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())
