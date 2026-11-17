import json
import tempfile
import unittest
from pathlib import Path

from exchange import Exchange


PURPOSE = "服务与设施复核"


class HandoverScenarioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "handover.db")
        svc = self.service
        # 景区与两任运营方
        svc.tenures.register_site("lake", "湖景景区", "2026-09-01", "登记处")
        svc.tenures.begin_tenure("t-old", "lake", "旧运营方", "2025-01-01", "2025-01-01", "登记处")
        svc.tenures.end_tenure("t-old", "2026-09-30", "2026-09-30", "登记处")
        svc.tenures.begin_tenure("t-new", "lake", "新运营方", "2026-10-01", "2026-10-01", "登记处")
        # 旧运营方上传的照片、投诉汇总两个来源，各有两个原件版本
        svc.catalog.register("photos", "旧运营方", "湖区", "review",
                             [("shot", "现场照片", "text", False)], "2026-08-01", site_id="lake")
        svc.catalog.register("complaints", "旧运营方", "湖区", "restricted",
                             [("summary", "投诉汇总", "text", True)], "2026-08-02", site_id="lake")
        svc.catalog.ingest("photo-v1", "photos", {"shot": "入口旧照"}, "2026-08-05")
        svc.catalog.ingest("photo-v2", "photos", {"shot": "码头旧照"}, "2026-08-06")
        svc.catalog.ingest("comp-v1", "complaints", {"summary": "三季度投诉"}, "2026-08-07")
        svc.catalog.ingest("comp-v2", "complaints", {"summary": "复核期投诉"}, "2026-08-08")
        # 辖区策略允许复核用途
        svc.policies.set("湖区", "review", PURPOSE, "allow", "2026-08-01", "主管部门")
        svc.policies.set("湖区", "restricted", PURPOSE, "allow", "2026-08-01", "主管部门")
        # 旧团队自己持有的来源级许可（不随经营权自动移交）
        svc.grants.issue("g-old", "photos", "旧运营方", PURPOSE, "2027-12-31", "2026-08-05")
        svc.grants.issue("g-old-comp", "complaints", "旧运营方", PURPOSE, "2027-12-31", "2026-08-07")
        # 经营权接手回执
        svc.handovers.record("h-1", "lake", "旧运营方", "新运营方", "2026-10-01",
                             "回执-HR-2026-001", "2026-10-01", "主管部门")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_lineage_tracks_operator_history(self):
        lineage = self.service.tenures.lineage("lake")
        self.assertEqual([row["operator"] for row in lineage], ["旧运营方", "新运营方"])
        self.assertEqual(self.service.tenures.operator_at("lake", "2026-09-15"), "旧运营方")
        self.assertEqual(self.service.tenures.operator_at("lake", "2026-10-15"), "新运营方")
        handover = self.service.handovers.for_site("lake")[0]
        self.assertEqual(handover["receipt"], "回执-HR-2026-001")

    def test_new_team_sees_sourced_but_unavailable_materials(self):
        listing = self.service.availability.site_listing("lake", "新运营方", PURPOSE, "2026-10-05")
        self.assertEqual(listing["operator_at"], "新运营方")
        statuses = {item["asset_id"]: item["status"] for item in listing["items"]}
        # 没有任何面向新团队的许可：看得到来源与摘要指纹，但全部暂不可用
        self.assertTrue(all(status == "unlicensed" for status in statuses.values()))
        self.assertEqual(set(statuses), {"photo-v1", "photo-v2", "comp-v1", "comp-v2"})
        # 清单不泄露原件正文
        self.assertNotIn("payload", json.dumps(listing, ensure_ascii=False))
        with self.assertRaises(PermissionError):
            self.service.catalog.open_asset("photo-v1", "新运营方", PURPOSE, "2026-10-05")

    def test_handover_receipt_does_not_grant_access(self):
        # 接手回执已存在，但新团队没有许可，交付关口必须拦截（组装只校验原件有效性）
        revision = self.service.products.assemble("dossier", "复核材料", ["photo-v1"],
                                                  "2026-10-06", "新运营方", site_id="lake")
        with self.assertRaises(PermissionError):
            self.service.delivery.send("d-blocked", "dossier", revision,
                                       "新运营方", PURPOSE, "2026-10-06")
        check = self.service.availability.check_references("dossier", revision,
                                                           "新运营方", PURPOSE, "2026-10-06")
        self.assertFalse(check["deliverable"])
        self.assertEqual(check["blocked"], ["photo-v1"])

    def test_resigned_licence_releases_only_scoped_versions(self):
        # 补签：只对 photo-v1 这一版本放行
        self.service.grants.issue("g-new-v1", "photos", "新运营方", PURPOSE,
                                  "2027-06-30", "2026-10-10", asset_ids=["photo-v1"])
        listing = self.service.availability.site_listing("lake", "新运营方", PURPOSE, "2026-10-11")
        statuses = {item["asset_id"]: item["status"] for item in listing["items"]}
        self.assertEqual(statuses["photo-v1"], "available")
        self.assertEqual(statuses["photo-v2"], "unlicensed")
        self.assertEqual(statuses["comp-v1"], "unlicensed")
        # 只放行相应版本：v1 可取，v2 仍被拒
        opened = self.service.catalog.open_asset("photo-v1", "新运营方", PURPOSE, "2026-10-11")
        self.assertIn("入口旧照", opened["payload"])
        with self.assertRaises(PermissionError):
            self.service.catalog.open_asset("photo-v2", "新运营方", PURPOSE, "2026-10-11")
        revision = self.service.products.assemble("dossier", "复核材料", ["photo-v1"],
                                                  "2026-10-12", "新运营方", site_id="lake")
        receipt = self.service.delivery.send("d-1", "dossier", revision,
                                             "新运营方", PURPOSE, "2026-10-12")
        evidence = json.loads(receipt["grant_evidence"])
        self.assertEqual(evidence[0]["grant_id"], "g-new-v1")
        self.assertEqual(receipt["operator_at_delivery"], "新运营方")

    def test_revocation_mid_handover_blocks_originals_even_with_receipt(self):
        self.service.grants.issue("g-new-v1", "photos", "新运营方", PURPOSE,
                                  "2027-06-30", "2026-10-10", asset_ids=["photo-v1"])
        revision = self.service.products.assemble("dossier", "复核材料", ["photo-v1"],
                                                  "2026-10-12", "新运营方", site_id="lake")
        receipt = self.service.delivery.send("d-1", "dossier", revision,
                                             "新运营方", PURPOSE, "2026-10-12")
        self.assertEqual(receipt["id"], "d-1")
        # 移交中途许可被撤销
        self.service.grants.revoke("g-new-v1", "2026-10-15", "旧运营方")
        # 已生成的回执仍在，但原件不得继续交付：取件被实时拦截
        with self.assertRaises(PermissionError):
            self.service.catalog.open_asset("photo-v1", "新运营方", PURPOSE, "2026-10-16")
        # 清单同步转为不可用
        listing = self.service.availability.site_listing("lake", "新运营方", PURPOSE, "2026-10-16")
        self.assertEqual(next(i for i in listing["items"] if i["asset_id"] == "photo-v1")["status"],
                         "unlicensed")
        # 历史回执原样保留，仍记录当时运营方与许可编号
        stored = self.service.connection.execute("SELECT * FROM deliveries WHERE id='d-1'").fetchone()
        self.assertEqual(stored["operator_at_delivery"], "新运营方")
        self.assertIn("g-new-v1", stored["grant_evidence"])
        # 审计留痕包含撤销与再次取件被拒
        actions = [row["action"] for row in self.service.history("photo-v1")]
        self.assertIn("asset.deny", actions)
        self.assertIn("grant.revoke", [row["action"] for row in self.service.history("g-new-v1")])

    def test_old_conclusion_keeps_operator_and_licence_basis(self):
        # 旧运营方在自己任期内完成的复核结论
        revision = self.service.products.assemble("old-review", "旧版复核结论", ["comp-v1"],
                                                  "2026-09-20", "旧运营方", site_id="lake")
        receipt = self.service.delivery.send("d-old", "old-review", revision,
                                             "旧运营方", PURPOSE, "2026-09-21")
        self.assertEqual(receipt["operator_at_delivery"], "旧运营方")
        evidence = json.loads(receipt["grant_evidence"])
        self.assertEqual(evidence[0]["grant_id"], "g-old-comp")
        # 经营权更替后历史回执不被改写
        self.service.grants.revoke("g-old-comp", "2026-10-20", "旧运营方")
        stored = self.service.connection.execute("SELECT * FROM deliveries WHERE id='d-old'").fetchone()
        self.assertEqual(stored["operator_at_delivery"], "旧运营方")
        self.assertIn("g-old-comp", stored["grant_evidence"])

    def test_cross_site_reference_rejected(self):
        self.service.tenures.register_site("hill", "山岭景区", "2026-09-01", "登记处")
        self.service.catalog.register("hill-src", "其他机构", "山区", "review",
                                      [("shot", "照片", "text", False)], "2026-09-02", site_id="hill")
        self.service.catalog.ingest("hill-item", "hill-src", {"shot": "山道"}, "2026-09-03")
        with self.assertRaises(ValueError):
            self.service.products.assemble("mixed", "混编材料", ["photo-v1", "hill-item"],
                                           "2026-10-06", "新运营方", site_id="lake")

    def test_invalid_handover_rejected(self):
        with self.assertRaises(ValueError):
            self.service.handovers.record("h-bad", "lake", "旧运营方", "旁观者",
                                          "2026-10-01", "回执-X", "2026-10-01", "主管部门")
        with self.assertRaises(ValueError):
            self.service.handovers.record("h-bad2", "lake", "旧运营方", "新运营方",
                                          "2026-03-01", "回执-Y", "2026-03-01", "主管部门")


if __name__ == "__main__":
    unittest.main()
