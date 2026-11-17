from .grants import Grants
from .policy import Policies


# 状态优先级：原件/来源失效最重，其次策略禁止，最后才是缺许可（有来源但暂不可用）。
STATUS_ORDER = {"inactive": 0, "policy_blocked": 1, "unlicensed": 2, "available": 3}


class Gate:
    """运营关系、材料许可与复核引用的交叉校验关口。

    所有判断都基于当前数据库状态实时计算：许可在移交中途被撤销时，
    即使此前已生成接手回执或交付回执，这里也不会再放行原件。
    """

    def __init__(self, connection):
        self.connection = connection
        self.grants = Grants(connection)
        self.policies = Policies(connection)

    def evaluate(self, asset, recipient, purpose, at):
        """评估单个原件对某领取方/用途在某时点的可用性。

        返回 dict：status、reasons、grant_id、policy_revision。
        """
        source_id = asset["source_id"]
        reasons = []
        if asset["state"] != "active" or not asset["source_active"]:
            reasons.append("inactive")
        grant_id = self.grants.permits(source_id, recipient, purpose, at, asset["id"])
        if not grant_id:
            reasons.append("grant")
        decision, policy_revision = self.policies.decision(
            asset["jurisdiction"], asset["classification"], purpose
        )
        if decision != "allow":
            reasons.append("policy")
        if "inactive" in reasons:
            status = "inactive"
        elif "policy" in reasons:
            status = "policy_blocked"
        elif "grant" in reasons:
            status = "unlicensed"
        else:
            status = "available"
        return {"status": status, "reasons": reasons,
                "grant_id": grant_id, "policy_revision": policy_revision}
