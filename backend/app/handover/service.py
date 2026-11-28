"""巡护接办授权领域服务。

覆盖业务规则：
  1. 威胁评估签发后，按影响段（东段/西段）下发巡护接办授权；
     公开处置范围（片区级）与现场人员可见的精确点位分开存储、分开呈现。
  2. 跨班组领取、提交均受班组实际巡护片区限制；越权请求的回执/错误响应
     一律不包含精确点位。
  3. 授权可在同片区班组间转交；重发凭幂等键只记一次交割。
  4. 转交后原班组在途日志可由指定的原现场人员补传，新任务只认当前持有班组。
  5. 巡护提交日志时校验现场任务授权，并冻结「核查当时的授权人与有效范围」快照。
  6. 只有已审阅的有效回执可供评估采用；只有实际巡护过的范围能调整当前评估。
  7. 采用结果回到威胁评估申请，作为缩小或保留影响范围的依据。

状态流转只在本服务内修改，路由层不做业务判断（与项目约定一致）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.handover.store import PERSON_TEAM, TEAM_ZONES, handover_store
from app.store import store

# 回执状态
RECEIPT_PENDING = "待审阅"
RECEIPT_VALID = "有效"
RECEIPT_REJECTED = "已驳回"

# 授权单状态
GRANT_OPEN = "待领取"
GRANT_CLAIMED = "已领取"
GRANT_TRANSFERRED = "已转交"
GRANT_CLOSED = "已关闭"

ROLE_REVIEWER = "审阅员"
ROLE_ISSUER = "签发员"
FIELD_ROLES = {"现场人员", ""}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class HandoverError(Exception):
    """业务校验失败；message 只含片区/编号级信息，严禁携带精确点位。"""


class HandoverService:
    # ------------------------------------------------------------------ 目录
    def roster(self) -> dict[str, Any]:
        return {
            "team_zones": {k: list(v) for k, v in TEAM_ZONES.items()},
            "person_team": dict(PERSON_TEAM),
        }

    def _team_of(self, person: str) -> str:
        team = PERSON_TEAM.get(person)
        if not team:
            raise HandoverError(f"现场人员「{person}」不在巡护人员目录中")
        return team

    def _zones_of(self, team: str) -> list[str]:
        zones = TEAM_ZONES.get(team)
        if zones is None:
            raise HandoverError(f"班组「{team}」不在巡护班组目录中")
        return list(zones)

    # ------------------------------------------------------------ 演示数据
    def reset_demo(self, issued_by: str = "签发员-林工") -> dict[str, Any]:
        """重建一套可演示数据：一条含东/西两段影响范围的已签发威胁评估。"""
        handover_store.reset()
        threat_rows = store.rows("threat_assessment")
        assessment_id = max((int(r.get("id", 0)) for r in threat_rows), default=0) + 1
        assessment = {
            "id": assessment_id,
            "评估对象": "云岭东麓羚牛栖息地",
            "威胁类别": "盗猎与人为干扰",
            "威胁程度": "高",
            "影响范围": "东段、西段（敏感点位另行下发）",
            "缓解建议": "分段巡护核查，按有效回执决定缩小或保留影响范围",
            "评估人": issued_by,
            "评估日期": datetime.now().date().isoformat(),
            "备注说明": "巡护接办授权演示评估单",
            "status": "已签发",
            "pending": False,
            "abnormal": False,
        }
        threat_rows.append(assessment)
        segments = [
            {
                "segment": "东段",
                "public_scope": f"威胁评估#{assessment_id} 东段公开处置范围：云岭东麓东段片区（片区级，不含坐标）",
                "points": [
                    {"point_id": "E-01", "name": "东段一号沟入口", "lat": 26.8121, "lng": 99.9312},
                    {"point_id": "E-02", "name": "东段山脊兽道", "lat": 26.8204, "lng": 99.9455},
                ],
            },
            {
                "segment": "西段",
                "public_scope": f"威胁评估#{assessment_id} 西段公开处置范围：云岭东麓西段片区（片区级，不含坐标）",
                "points": [
                    {"point_id": "W-01", "name": "西段水源地", "lat": 26.7955, "lng": 99.8721},
                ],
            },
        ]
        grants = self.issue_grants(assessment_id, segments, issued_by=issued_by)
        return {"assessment_id": assessment_id, "grants": [self.public_view(g) for g in grants]}

    # ------------------------------------------------------------ 授权签发
    def issue_grants(
        self,
        assessment_id: int,
        segments: list[dict[str, Any]],
        *,
        issued_by: str,
    ) -> list[dict[str, Any]]:
        assessment = store.find("threat_assessment", assessment_id)
        if assessment is None:
            raise HandoverError(f"威胁评估 {assessment_id} 不存在")
        if assessment.get("status") != "已签发":
            raise HandoverError(
                f"威胁评估 {assessment_id} 当前状态为「{assessment.get('status')}」，"
                "只有已签发的评估才能下发巡护接办授权"
            )
        if not segments:
            raise HandoverError("至少需要一个影响段才能下发授权")
        grants: list[dict[str, Any]] = []
        for item in segments:
            segment = str(item.get("segment", "")).strip()
            if not segment:
                raise HandoverError("影响段名称不能为空")
            if handover_store.find_grant_by_segment(assessment_id, segment):
                raise HandoverError(f"评估 {assessment_id} 的{segment}授权已存在，不得重复签发")
            points = [dict(p) for p in item.get("points", [])]
            grant = {
                "id": handover_store.next_grant_id(),
                "assessment_id": assessment_id,
                "segment": segment,
                "public_scope": str(item.get("public_scope") or f"{segment}片区公开处置范围"),
                "precise_points": points,
                "status": GRANT_OPEN,
                "current_team": None,
                "current_holder": None,
                "issued_by": issued_by,
                "issued_at": _now(),
                "claims": [],          # 领取历史
                "transfer_ids": [],    # 交割链
                "legacy_submitters": [],  # 转交后仍可补传在途日志的原现场人员
                "handover_at": None,
            }
            handover_store.grants.append(grant)
            grants.append(grant)
        return grants

    # ------------------------------------------------------------ 领取
    def claim_grant(self, grant_id: int, person: str) -> dict[str, Any]:
        grant = self._require_grant(grant_id)
        team = self._team_of(person)
        zones = self._zones_of(team)
        if grant["segment"] not in zones:
            # 越权：返回信息只到片区级，不含任何点位
            raise HandoverError(
                f"越权拦截：{team}实际巡护片区为{'、'.join(zones)}，"
                f"不包含{grant['segment']}，不能领取该段巡护任务"
            )
        if grant["status"] == GRANT_CLOSED:
            raise HandoverError(f"授权单 {grant_id} 已关闭，不能领取")
        if grant["status"] == GRANT_CLAIMED and grant["current_team"] == team:
            raise HandoverError(f"{team}已持有授权单 {grant_id}，无需重复领取")
        if grant["status"] == GRANT_CLAIMED:
            raise HandoverError(
                f"授权单 {grant_id} 现由{grant['current_team']}持有，"
                "跨班组接续须走转交流程而非直接领取"
            )
        grant["current_team"] = team
        grant["current_holder"] = person
        grant["status"] = GRANT_CLAIMED
        grant["claims"].append({"team": team, "person": person, "at": _now()})
        return grant

    # ------------------------------------------------------------ 转交（交割）
    def transfer_grant(
        self,
        grant_id: int,
        *,
        by_person: str,
        to_team: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        grant = self._require_grant(grant_id)
        key = f"transfer:{idempotency_key}"
        cached = handover_store.idempotency.get(key)
        if cached is not None:
            # 巡护核查重发只记一次交割：幂等命中直接回原交割记录
            event = handover_store.find_transfer(int(cached["transfer_id"]))
            assert event is not None
            event["_replayed"] = True
            return event

        from_team = self._team_of(by_person)
        to_zones = self._zones_of(to_team)
        if grant["segment"] not in to_zones:
            raise HandoverError(
                f"越权拦截：{to_team}实际巡护片区为{'、'.join(to_zones)}，"
                f"不包含{grant['segment']}，不能接办该段授权"
            )
        if grant["current_team"] != from_team:
            raise HandoverError(
                f"只有当前持有班组（{grant['current_team'] or '无人'}）才能转交授权单 {grant_id}"
            )
        if to_team == from_team:
            raise HandoverError("接办班组与持有班组相同，无需转交")

        handover_at = _now()
        event = {
            "id": handover_store.next_transfer_id(),
            "grant_id": grant_id,
            "assessment_id": grant["assessment_id"],
            "segment": grant["segment"],
            "from_team": from_team,
            "to_team": to_team,
            "by_person": by_person,
            "at": handover_at,
            "idempotency_key": idempotency_key,
            "valid_scope_snapshot": {
                "授权人": grant["issued_by"],
                "有效范围": [grant["segment"]],
                "转出班组": from_team,
                "接办班组": to_team,
                "快照时间": handover_at,
            },
            "_replayed": False,
        }
        handover_store.transfers.append(event)
        handover_store.idempotency[key] = {"transfer_id": event["id"]}

        # 原现场人员进入在途补传名单：转交前已产生的日志仍可由其上交
        legacy = {
            "person": grant["current_holder"],
            "team": from_team,
            "handover_at": handover_at,
            "transfer_id": event["id"],
            "remaining": True,
        }
        grant["legacy_submitters"].append(legacy)
        grant["transfer_ids"].append(event["id"])
        grant["current_team"] = to_team
        grant["current_holder"] = None
        grant["status"] = GRANT_TRANSFERRED
        grant["handover_at"] = handover_at
        return event

    def intransit_candidates(self, grant_id: int) -> dict[str, Any]:
        """接班员查询：该段在途日志还能由谁上交。"""
        grant = self._require_grant(grant_id)
        candidates = [
            {
                "person": item["person"],
                "team": item["team"],
                "handover_at": item["handover_at"],
                "remaining": item["remaining"],
            }
            for item in grant["legacy_submitters"]
        ]
        return {
            "grant_id": grant_id,
            "segment": grant["segment"],
            "current_team": grant["current_team"],
            "intransit_submitters": candidates,
        }

    # ------------------------------------------------------------ 提交巡护日志
    def submit_receipt(
        self,
        grant_id: int,
        *,
        person: str,
        covered_zones: list[str],
        point_ids: list[str] | None = None,
        log_time: str | None = None,
        in_transit: bool = False,
        findings: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        grant = self._require_grant(grant_id)
        team = self._team_of(person)
        team_zones = self._zones_of(team)
        point_ids = point_ids or []
        log_time = log_time or _now()

        if idempotency_key:
            cached = handover_store.idempotency.get(f"receipt:{idempotency_key}")
            if cached is not None:
                repeat = handover_store.find_receipt(int(cached["receipt_id"]))
                assert repeat is not None
                repeat["_replayed"] = True
                return repeat

        # 片区校验：跨班组提交受实际巡护片区限制
        if grant["segment"] not in team_zones:
            raise HandoverError(
                f"越权拦截：{team}实际巡护片区为{'、'.join(team_zones)}，"
                f"不包含{grant['segment']}，提交被拒绝"
            )
        bad_zones = [z for z in covered_zones if not str(z).startswith(grant["segment"])]
        if bad_zones:
            raise HandoverError(
                f"越权拦截：申报巡护范围 {'、'.join(bad_zones)} 不属于{grant['segment']}，提交被拒绝"
            )
        known_points = {p["point_id"] for p in grant["precise_points"]}
        unknown = [pid for pid in point_ids if pid not in known_points]
        if unknown:
            raise HandoverError("申报点位不在该授权单下发的敏感点位清单内，提交被拒绝")

        if in_transit:
            return self._submit_intransit(
                grant, person=person, team=team, covered_zones=covered_zones,
                point_ids=point_ids, log_time=log_time, findings=findings,
                idempotency_key=idempotency_key,
            )

        # 常规提交：只认当前持有班组
        if grant["current_team"] != team:
            raise HandoverError(
                f"授权单 {grant_id} 当前由{grant['current_team'] or '无人'}持有，"
                f"{team}无现场任务授权；如属转交前在途日志请走在途补传"
            )
        snapshot = {
            "授权人": grant["issued_by"],
            "提交时持有班组": team,
            "有效范围": [grant["segment"]],
            "授权单状态": grant["status"],
            "快照时间": _now(),
        }
        return self._build_receipt(
            grant, person=person, team=team, covered_zones=covered_zones,
            point_ids=point_ids, log_time=log_time, findings=findings,
            kind="现场提交", snapshot=snapshot, idempotency_key=idempotency_key,
        )

    def _submit_intransit(
        self,
        grant: dict[str, Any],
        *,
        person: str,
        team: str,
        covered_zones: list[str],
        point_ids: list[str],
        log_time: str,
        findings: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        legacy = next(
            (item for item in grant["legacy_submitters"]
             if item["person"] == person and item["remaining"]),
            None,
        )
        if legacy is None:
            raise HandoverError(
                f"{person}不在授权单 {grant['id']} 的在途日志补传名单内，不能以上交在途日志"
            )
        if log_time > legacy["handover_at"]:
            raise HandoverError(
                "在途日志的巡查时间必须早于交割时间，交割后的新任务由当前持有班组提交"
            )
        # 冻结核查当时的授权人与有效范围（按交割前状态）
        snapshot = {
            "授权人": grant["issued_by"],
            "提交时持有班组": team,
            "有效范围": [grant["segment"]],
            "授权单状态": GRANT_CLAIMED,
            "关联交割": legacy["transfer_id"],
            "快照时间": _now(),
            "说明": "转交前已产生、转交后补传的在途日志，授权快照按交割前状态冻结",
        }
        receipt = self._build_receipt(
            grant, person=person, team=team, covered_zones=covered_zones,
            point_ids=point_ids, log_time=log_time, findings=findings,
            kind="在途补传", snapshot=snapshot, idempotency_key=idempotency_key,
        )
        legacy["remaining"] = False
        return receipt

    def _build_receipt(
        self,
        grant: dict[str, Any],
        *,
        person: str,
        team: str,
        covered_zones: list[str],
        point_ids: list[str],
        log_time: str,
        findings: str,
        kind: str,
        snapshot: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        points = [dict(p) for p in grant["precise_points"] if p["point_id"] in point_ids]
        receipt = {
            "id": handover_store.next_receipt_id(),
            "grant_id": grant["id"],
            "assessment_id": grant["assessment_id"],
            "segment": grant["segment"],
            "kind": kind,
            "submitter": person,
            "team": team,
            "covered_zones": list(covered_zones),
            "precise_points": points,
            "log_time": log_time,
            "findings": findings,
            "status": RECEIPT_PENDING,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": "",
            "adopted": False,
            "adoption_ids": [],
            "authorization_snapshot": snapshot,
            "submitted_at": _now(),
            "_replayed": False,
        }
        handover_store.receipts.append(receipt)
        if idempotency_key:
            handover_store.idempotency[f"receipt:{idempotency_key}"] = {"receipt_id": receipt["id"]}
        return receipt

    # ------------------------------------------------------------ 审阅
    def review_receipt(
        self,
        receipt_id: int,
        *,
        reviewer: str,
        valid: bool,
        note: str = "",
    ) -> dict[str, Any]:
        receipt = self._require_receipt(receipt_id)
        if receipt["status"] != RECEIPT_PENDING:
            raise HandoverError(f"回执 {receipt_id} 已审阅，不能重复审阅")
        receipt["status"] = RECEIPT_VALID if valid else RECEIPT_REJECTED
        receipt["reviewed_by"] = reviewer
        receipt["reviewed_at"] = _now()
        receipt["review_note"] = note
        return receipt

    # ------------------------------------------------------------ 评估采用
    def adopt_receipts(
        self,
        assessment_id: int,
        *,
        receipt_ids: list[int],
        decision: str,
        issuer: str,
        evidence_scope: list[str] | None = None,
    ) -> dict[str, Any]:
        if decision not in ("缩小", "保留"):
            raise HandoverError("范围调整结论只允许「缩小」或「保留」")
        if not receipt_ids:
            raise HandoverError("至少选择一份回执才能形成评估更新依据")
        assessment = store.find("threat_assessment", assessment_id)
        if assessment is None:
            raise HandoverError(f"威胁评估 {assessment_id} 不存在")

        chosen: list[dict[str, Any]] = []
        for rid in receipt_ids:
            receipt = handover_store.find_receipt(rid)
            if receipt is None:
                raise HandoverError(f"回执 {rid} 不存在")
            if int(receipt["assessment_id"]) != assessment_id:
                raise HandoverError(f"回执 {rid} 不属于威胁评估 {assessment_id}，不能采用")
            # 只有已审阅的有效回执可供评估采用
            if receipt["status"] != RECEIPT_VALID:
                raise HandoverError(
                    f"回执 {rid} 当前状态为「{receipt['status']}」，"
                    "只有已审阅的有效回执可供评估采用"
                )
            chosen.append(receipt)

        # 只有实际巡护过的范围才能用于调整当前评估
        patrolled = sorted({zone for r in chosen for zone in r["covered_zones"]})
        if evidence_scope:
            overreach = [z for z in evidence_scope if z not in patrolled]
            if overreach:
                raise HandoverError(
                    f"申请调整范围 {'、'.join(overreach)} 没有任何有效回执的实际巡护记录支撑，不能用于评估调整"
                )
        applied_scope = evidence_scope or patrolled

        adoption = {
            "id": handover_store.next_adoption_id(),
            "assessment_id": assessment_id,
            "receipt_ids": [r["id"] for r in chosen],
            "decision": decision,
            "applied_scope": applied_scope,
            "patrolled_evidence": patrolled,
            "issuer": issuer,
            "at": _now(),
        }
        handover_store.adoptions.append(adoption)
        for receipt in chosen:
            receipt["adopted"] = True
            receipt["adoption_ids"].append(adoption["id"])

        # 审阅后的结果回到评估申请更新
        assessment.setdefault("评估更新依据", [])
        assessment["评估更新依据"].append(
            f"采用单#{adoption['id']}：回执 {'、'.join('#' + str(r['id']) for r in chosen)}；"
            f"实际巡护范围 {'、'.join(patrolled)}；结论：{decision}影响范围"
        )
        assessment["有效回执"] = sorted({
            *[str(x) for x in assessment.get("有效回执", [])],
            *[str(r["id"]) for r in chosen],
        })
        assessment["实际巡护范围"] = patrolled
        assessment["范围调整结论"] = f"{decision}影响范围"
        assessment["status"] = "需更新"
        assessment["pending"] = True
        return {
            "adoption": adoption,
            "assessment_id": assessment_id,
            "assessment_status": assessment["status"],
        }

    def adoptable_receipts(self, assessment_id: int) -> dict[str, Any]:
        """签发员视角：评估单下可供采用的回执（仅已审阅有效）与全部回执状态。"""
        grants = handover_store.grants_for_assessment(assessment_id)
        receipts = [
            r for g in grants for r in handover_store.receipts_for_grant(int(g["id"]))
        ]
        return {
            "assessment_id": assessment_id,
            "adoptable": [
                self.receipt_view(r, role=ROLE_ISSUER)
                for r in receipts if r["status"] == RECEIPT_VALID
            ],
            "all_receipts": [
                {
                    "id": r["id"],
                    "segment": r["segment"],
                    "kind": r["kind"],
                    "team": r["team"],
                    "submitter": r["submitter"],
                    "status": r["status"],
                    "adopted": r["adopted"],
                    "covered_zones": r["covered_zones"],
                }
                for r in receipts
            ],
        }

    # ------------------------------------------------------------ 视图与脱敏
    def _require_grant(self, grant_id: int) -> dict[str, Any]:
        grant = handover_store.find_grant(grant_id)
        if grant is None:
            raise HandoverError(f"巡护接办授权单 {grant_id} 不存在")
        return grant

    def _require_receipt(self, receipt_id: int) -> dict[str, Any]:
        receipt = handover_store.find_receipt(receipt_id)
        if receipt is None:
            raise HandoverError(f"巡护回执 {receipt_id} 不存在")
        return receipt

    @staticmethod
    def _masked_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # 越权/公开视图：只保留点位数量与编号，坐标与名称一律不下发
        return [
            {"point_id": p["point_id"], "name": "敏感点位（无权查看）", "lat": None, "lng": None}
            for p in points
        ]

    def public_view(self, grant: dict[str, Any]) -> dict[str, Any]:
        """公开处置范围视图：任何场景都不含精确点位。"""
        return {
            "id": grant["id"],
            "assessment_id": grant["assessment_id"],
            "segment": grant["segment"],
            "public_scope": grant["public_scope"],
            "sensitive_point_count": len(grant["precise_points"]),
            "status": grant["status"],
            "current_team": grant["current_team"],
        }

    def grant_view(
        self,
        grant: dict[str, Any],
        *,
        team: str | None = None,
        role: str = "",
    ) -> dict[str, Any]:
        view = self.public_view(grant)
        view.update({
            "current_holder": grant["current_holder"],
            "issued_by": grant["issued_by"],
            "issued_at": grant["issued_at"],
            "claims": list(grant["claims"]),
            "transfer_ids": list(grant["transfer_ids"]),
        })
        # 精确点位：签发/审阅岗位，或当前持有班组的现场人员可见
        full = role in (ROLE_REVIEWER, ROLE_ISSUER) or (
            team is not None and grant["current_team"] == team
        )
        if full:
            view["precise_points"] = [dict(p) for p in grant["precise_points"]]
        else:
            view["precise_points"] = self._masked_points(grant["precise_points"])
        return view

    def receipt_view(
        self,
        receipt: dict[str, Any],
        *,
        team: str | None = None,
        role: str = "",
    ) -> dict[str, Any]:
        grant = handover_store.find_grant(int(receipt["grant_id"]))
        view = {k: v for k, v in receipt.items() if not k.startswith("_")}
        full = role in (ROLE_REVIEWER, ROLE_ISSUER) or (
            grant is not None and team is not None and grant["current_team"] == team
            and receipt["kind"] != "在途补传"
        )
        if not full:
            # 越权视图与在途补传回执：不包含精确点位
            view["precise_points"] = self._masked_points(receipt["precise_points"])
        return view

    def list_grants(
        self,
        *,
        assessment_id: int | None = None,
        team: str | None = None,
        role: str = "",
    ) -> list[dict[str, Any]]:
        grants = handover_store.grants
        if assessment_id is not None:
            grants = handover_store.grants_for_assessment(assessment_id)
        return [self.grant_view(g, team=team, role=role) for g in grants]

    def list_receipts(
        self,
        *,
        grant_id: int | None = None,
        team: str | None = None,
        role: str = "",
    ) -> list[dict[str, Any]]:
        if grant_id is not None:
            receipts = handover_store.receipts_for_grant(grant_id)
        else:
            receipts = list(handover_store.receipts)
        return [self.receipt_view(r, team=team, role=role) for r in receipts]

    def list_transfers(self, grant_id: int | None = None) -> list[dict[str, Any]]:
        events = handover_store.transfers
        if grant_id is not None:
            events = [e for e in events if int(e["grant_id"]) == grant_id]
        return [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]


handover_service = HandoverService()
