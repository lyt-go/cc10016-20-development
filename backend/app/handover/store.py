"""巡护接办授权内存仓库。

与通用 store 分离：授权、交割、回执属于敏感点位核查的独立领域，
需要单独维护班组/片区目录与逐段授权状态，避免污染 18 个通用模块。

真实项目里这里会换成数据库访问层；当前只依赖标准库，保证克隆即可运行。
"""
from __future__ import annotations

from typing import Any


# 班组 -> 实际巡护片区。领取、提交都受此限制：
# 甲、乙两班负责东段，丙班负责西段，救护支援班按授权接办东段。
TEAM_ZONES: dict[str, list[str]] = {
    "甲班": ["东段"],
    "乙班": ["东段"],
    "丙班": ["西段"],
    "救护支援班": ["东段"],
}

# 现场人员目录：人员 -> 所属班组。
PERSON_TEAM: dict[str, str] = {
    "甲班-赵巡": "甲班",
    "甲班-钱巡": "甲班",
    "乙班-孙巡": "乙班",
    "乙班-李巡": "乙班",
    "丙班-周巡": "丙班",
    "丙班-吴巡": "丙班",
    "救护-郑班": "救护支援班",
    "救护-王班": "救护支援班",
}


class HandoverStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """清空并恢复演示数据；测试之间调用以获得确定性状态。"""
        # 授权单：威胁评估的每个影响段一条
        self.grants: list[dict[str, Any]] = []
        # 交割事件：每次成功转交一条，重发只记一次
        self.transfers: list[dict[str, Any]] = []
        # 巡护回执（现场提交日志）
        self.receipts: list[dict[str, Any]] = []
        # 评估采用记录
        self.adoptions: list[dict[str, Any]] = []
        self._grant_seq = 0
        self._transfer_seq = 0
        self._receipt_seq = 0
        self._adoption_seq = 0
        # 幂等键 -> 已生成的实体 id
        self.idempotency: dict[str, dict[str, Any]] = {}

    def next_grant_id(self) -> int:
        self._grant_seq += 1
        return self._grant_seq

    def next_transfer_id(self) -> int:
        self._transfer_seq += 1
        return self._transfer_seq

    def next_receipt_id(self) -> int:
        self._receipt_seq += 1
        return self._receipt_seq

    def next_adoption_id(self) -> int:
        self._adoption_seq += 1
        return self._adoption_seq

    # ---- 授权单查询 ----
    def find_grant(self, grant_id: int) -> dict[str, Any] | None:
        for grant in self.grants:
            if int(grant["id"]) == grant_id:
                return grant
        return None

    def find_grant_by_segment(self, assessment_id: int, segment: str) -> dict[str, Any] | None:
        for grant in self.grants:
            if int(grant["assessment_id"]) == assessment_id and grant["segment"] == segment:
                return grant
        return None

    def grants_for_assessment(self, assessment_id: int) -> list[dict[str, Any]]:
        return [g for g in self.grants if int(g["assessment_id"]) == assessment_id]

    # ---- 交割查询 ----
    def find_transfer(self, transfer_id: int) -> dict[str, Any] | None:
        for event in self.transfers:
            if int(event["id"]) == transfer_id:
                return event
        return None

    # ---- 回执查询 ----
    def find_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        for receipt in self.receipts:
            if int(receipt["id"]) == receipt_id:
                return receipt
        return None

    def receipts_for_grant(self, grant_id: int) -> list[dict[str, Any]]:
        return [r for r in self.receipts if int(r["grant_id"]) == grant_id]


handover_store = HandoverStore()
