import argparse
import json

from .service import Exchange

PURPOSE = "服务与设施复核"


def show(title, payload):
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def main():
    parser = argparse.ArgumentParser(description="景区资料本地协作演练")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    service = Exchange(args.database)
    try:
        # 1. 景区与运营关系沿革
        service.tenures.register_site("lake", "湖景景区", "2026-09-01", "登记处")
        service.tenures.begin_tenure("t-old", "lake", "旧运营方", "2025-01-01", "2025-01-01", "登记处")
        service.tenures.end_tenure("t-old", "2026-09-30", "2026-09-30", "登记处")
        service.tenures.begin_tenure("t-new", "lake", "新运营方", "2026-10-01", "2026-10-01", "登记处")
        show("运营关系沿革", service.tenures.lineage("lake"))

        # 2. 旧运营方上传的照片与投诉材料
        service.catalog.register("photos", "旧运营方", "湖区", "review",
                                 [("shot", "现场照片", "text", False)], "2026-08-01", site_id="lake")
        service.catalog.ingest("photo-v1", "photos", {"shot": "入口旧照"}, "2026-08-05")
        service.catalog.ingest("photo-v2", "photos", {"shot": "码头旧照"}, "2026-08-06")
        service.policies.set("湖区", "review", PURPOSE, "allow", "2026-08-01", "主管部门")
        service.grants.issue("g-old", "photos", "旧运营方", PURPOSE, "2027-12-31", "2026-08-05")

        # 3. 经营权接手：回执只记录交接事实，不附带材料使用权
        service.handovers.record("h-1", "lake", "旧运营方", "新运营方", "2026-10-01",
                                 "回执-HR-2026-001", "2026-10-01", "主管部门")
        listing = service.availability.site_listing("lake", "新运营方", PURPOSE, "2026-10-05")
        show("接手后新团队看到的材料（有来源但暂不可用）",
             [{"asset_id": i["asset_id"], "status": i["status"], "reasons": i["reasons"]}
              for i in listing["items"]])

        # 4. 补签版本级许可：只放行 photo-v1
        service.grants.issue("g-new-v1", "photos", "新运营方", PURPOSE,
                             "2027-06-30", "2026-10-10", asset_ids=["photo-v1"])
        listing = service.availability.site_listing("lake", "新运营方", PURPOSE, "2026-10-11")
        show("补签后清单（仅相应版本放行）",
             [{"asset_id": i["asset_id"], "status": i["status"], "grant_id": i["grant_id"]}
              for i in listing["items"]])

        # 5. 复核材料引用与交付，回执快照当时运营方和许可依据
        revision = service.products.assemble("dossier", "服务设施复核", ["photo-v1"],
                                             "2026-10-12", "新运营方", site_id="lake")
        receipt = service.delivery.send("d-1", "dossier", revision,
                                        "新运营方", PURPOSE, "2026-10-12")
        show("交付回执（含运营方与许可依据快照）",
             {"id": receipt["id"], "operator_at_delivery": receipt["operator_at_delivery"],
              "grant_evidence": json.loads(receipt["grant_evidence"])})

        # 6. 移交中途许可撤销：回执仍在，但原件不再放行
        service.grants.revoke("g-new-v1", "2026-10-15", "旧运营方")
        try:
            service.catalog.open_asset("photo-v1", "新运营方", PURPOSE, "2026-10-16")
        except PermissionError as denied:
            show("撤销后再次取件被拒", denied.args[0])
        show("历史交付回执保持原样",
             {"id": receipt["id"], "operator_at_delivery": receipt["operator_at_delivery"],
              "grant_evidence": json.loads(receipt["grant_evidence"])})
    finally:
        service.close()


if __name__ == "__main__":
    main()
