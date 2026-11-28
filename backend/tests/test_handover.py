"""巡护接办授权领域测试。

覆盖题目给出的完整业务链路：
  - 签发后按东/西两段下发授权，公开处置范围与精确点位分离
  - 跨班组领取/提交受实际巡护片区限制，越权回执不含精确点位
  - 甲班领取东段后转交乙班，重发只记一次交割
  - 转交后在途日志的补传资格、西段巡护不受影响
  - 审阅后有效回执才能被评估采用，且只能调整实际巡护过的范围
  - 评估复核旧回执时可看到核查当时的授权人与有效范围快照

可直接运行：python3 backend/tests/test_handover.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from app.handover.router import (
    AdoptPayload,
    ClaimPayload,
    ReviewPayload,
    SubmitPayload,
    TransferPayload,
    adopt_receipts,
    claim_grant,
    get_grant,
    intransit_candidates,
    list_grants,
    list_transfers,
    reset_demo,
    review_receipt,
    submit_receipt,
)
from app.handover.service import (
    GRANT_CLAIMED,
    GRANT_OPEN,
    GRANT_TRANSFERRED,
    RECEIPT_PENDING,
    RECEIPT_REJECTED,
    RECEIPT_VALID,
    HandoverError,
    handover_service,
)
from app.handover.store import PERSON_TEAM, TEAM_ZONES, handover_store
from app.store import store

JIA = "甲班-赵巡"
YI = "乙班-孙巡"
BING = "丙班-周巡"
REVIEWER = "审阅员-秦工"
ISSUER = "签发员-林工"
EARLY_TIME = "2026-01-01T08:00:00"
FUTURE_TIME = "2099-01-01T00:00:00"


class HandoverTestCase(unittest.TestCase):
    def setUp(self) -> None:
        demo = reset_demo(type("P", (), {"issued_by": ISSUER})())
        self.assessment_id = demo["assessment_id"]
        grants = handover_service.list_grants(assessment_id=self.assessment_id)
        self.east_grant_id = next(g["id"] for g in grants if g["segment"] == "东段")
        self.west_grant_id = next(g["id"] for g in grants if g["segment"] == "西段")

    # ------------------------------------------------------------ 1. 授权下发与点位分离
    def test_grants_issued_per_segment_without_public_coordinates(self):
        grants = list_grants(assessment_id=self.assessment_id)
        self.assertEqual(len(grants["items"]), 2)
        for grant in grants["items"]:
            self.assertIn("public_scope", grant)
            # 公开/列表视图只给脱敏点位：保留编号结构，坐标必须为空
            self.assertTrue(all(p["lat"] is None and p["lng"] is None
                                for p in grant["precise_points"]))
            self.assertNotIn("26.8", str(grant))
            self.assertGreaterEqual(grant["sensitive_point_count"], 1)
            self.assertEqual(grant["status"], GRANT_OPEN)

    def test_holder_sees_points_but_other_team_does_not(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        holder_view = get_grant(self.east_grant_id, team="甲班")
        self.assertTrue(
            all(p["lat"] is not None for p in holder_view["precise_points"]),
            "持有班组现场人员应能看到精确点位",
        )
        other_view = get_grant(self.east_grant_id, team="乙班")
        self.assertTrue(
            all(p["lat"] is None for p in other_view["precise_points"]),
            "非授权班组只能看到脱敏点位",
        )
        self.assertNotIn("一号沟", str(other_view))

    # ------------------------------------------------------------ 2. 片区限制
    def test_cross_zone_claim_blocked_without_point_leak(self):
        with self.assertRaises(HTTPException) as ctx:
            claim_grant(self.east_grant_id, ClaimPayload(person=BING))
        self.assertEqual(ctx.exception.status_code, 400)
        detail = str(ctx.exception.detail)
        self.assertIn("越权拦截", detail)
        self.assertNotIn("lat", detail)
        self.assertNotIn("E-0", detail)
        # 被拒后授权单仍处于待领取
        self.assertEqual(handover_service._require_grant(self.east_grant_id)["status"], GRANT_OPEN)

    def test_cross_zone_submit_blocked(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        with self.assertRaises(HTTPException) as ctx:
            submit_receipt(
                self.east_grant_id,
                SubmitPayload(
                    person=BING,
                    covered_zones=["东段-越权片区"],
                    point_ids=["E-01"],
                ),
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertNotIn("26.8", str(ctx.exception.detail))

    def test_unknown_point_rejected(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        with self.assertRaises(HTTPException):
            submit_receipt(
                self.east_grant_id,
                SubmitPayload(person=JIA, covered_zones=["东段-一号沟片区"], point_ids=["X-99"]),
            )

    # ------------------------------------------------------------ 3. 领取、转交与幂等
    def test_claim_then_transfer_and_idempotent_replay(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        grant = handover_service._require_grant(self.east_grant_id)
        self.assertEqual(grant["status"], GRANT_CLAIMED)
        self.assertEqual(grant["current_team"], "甲班")

        payload = TransferPayload(
            by_person=JIA, to_team="乙班", idempotency_key="east-jia-to-yi-001")
        first = handover_service.transfer_grant(
            self.east_grant_id,
            by_person=JIA, to_team="乙班", idempotency_key="east-jia-to-yi-001",
        )
        # 重发：同一幂等键，只记一次交割
        second = handover_service.transfer_grant(
            self.east_grant_id,
            by_person=JIA, to_team="乙班", idempotency_key="east-jia-to-yi-001",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["_replayed"])
        self.assertEqual(len(list_transfers(self.east_grant_id)["items"]), 1)

        grant = handover_service._require_grant(self.east_grant_id)
        self.assertEqual(grant["status"], GRANT_TRANSFERRED)
        self.assertEqual(grant["current_team"], "乙班")
        self.assertEqual(grant["transfer_ids"], [first["id"]])
        # 交割快照记录核查当时的授权人与有效范围
        self.assertEqual(first["valid_scope_snapshot"]["授权人"], ISSUER)
        self.assertEqual(first["valid_scope_snapshot"]["有效范围"], ["东段"])

    def test_transfer_to_wrong_zone_team_blocked(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        with self.assertRaises(HandoverError):
            handover_service.transfer_grant(
                self.east_grant_id,
                by_person=JIA, to_team="丙班", idempotency_key="bad-transfer",
            )

    def test_west_segment_patrol_remains_normal(self):
        # 东段怎么交接都不影响西段：丙班正常领取西段并提交
        claim_grant(self.west_grant_id, ClaimPayload(person=BING))
        result = submit_receipt(
            self.west_grant_id,
            SubmitPayload(
                person=BING,
                covered_zones=["西段-水源片区"],
                point_ids=["W-01"],
                findings="西段水源地未见异常",
            ),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["receipt"]["segment"], "西段")

    # ------------------------------------------------------------ 4. 在途日志与接班查询
    def test_intransit_log_continuity_after_transfer(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        handover_service.transfer_grant(
            self.east_grant_id,
            by_person=JIA, to_team="乙班", idempotency_key="east-h-1",
        )
        # 接班员查询：东段在途日志还能由谁上交
        info = intransit_candidates(self.east_grant_id)
        self.assertEqual(info["current_team"], "乙班")
        self.assertEqual([c["person"] for c in info["intransit_submitters"]], [JIA])

        # 原班组交割后的常规提交被拒绝
        with self.assertRaises(HTTPException):
            submit_receipt(
                self.east_grant_id,
                SubmitPayload(person=JIA, covered_zones=["东段-山脊片区"], point_ids=["E-02"]),
            )
        # 在途日志：巡查时间早于交割，可由原人员补传
        intransit = submit_receipt(
            self.east_grant_id,
            SubmitPayload(
                person=JIA,
                covered_zones=["东段-一号沟片区"],
                point_ids=["E-01"],
                log_time=EARLY_TIME,
                in_transit=True,
                findings="交割前已巡一号沟，盗猎痕迹已清除",
            ),
        )
        self.assertEqual(intransit["receipt"]["kind"], "在途补传")
        self.assertEqual(intransit["receipt"]["status"], RECEIPT_PENDING)
        # 补传视图对非授权方脱敏
        self.assertTrue(all(p["lat"] is None for p in intransit["receipt"]["precise_points"]))
        # 快照冻结核查当时的授权人与有效范围
        snap = intransit["receipt"]["authorization_snapshot"]
        self.assertEqual(snap["授权人"], ISSUER)
        self.assertEqual(snap["有效范围"], ["东段"])
        self.assertIn("关联交割", snap)

        # 同一在途人员只有一次补传资格
        with self.assertRaises(HTTPException):
            submit_receipt(
                self.east_grant_id,
                SubmitPayload(
                    person=JIA, covered_zones=["东段-一号沟片区"], point_ids=["E-01"],
                    log_time=EARLY_TIME, in_transit=True,
                ),
            )
        # 交割后的时间不能冒充在途日志
        with self.assertRaises(HTTPException):
            submit_receipt(
                self.east_grant_id,
                SubmitPayload(
                    person=JIA, covered_zones=["东段-一号沟片区"], point_ids=["E-01"],
                    log_time=FUTURE_TIME, in_transit=True,
                ),
            )

    def test_new_holder_submits_field_log(self):
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        handover_service.transfer_grant(
            self.east_grant_id,
            by_person=JIA, to_team="乙班", idempotency_key="east-h-2",
        )
        result = submit_receipt(
            self.east_grant_id,
            SubmitPayload(
                person=YI,
                covered_zones=["东段-山脊片区"],
                point_ids=["E-02"],
                findings="乙班接班后核查山脊兽道，威胁减轻",
            ),
        )
        self.assertEqual(result["receipt"]["kind"], "现场提交")
        self.assertEqual(result["receipt"]["team"], "乙班")
        # 持有班组自己的回执可见坐标
        self.assertTrue(all(p["lat"] is not None for p in result["receipt"]["precise_points"]))

    # ------------------------------------------------------------ 5. 审阅与评估采用
    def _prepare_east_receipts(self) -> tuple[int, int]:
        claim_grant(self.east_grant_id, ClaimPayload(person=JIA))
        handover_service.transfer_grant(
            self.east_grant_id,
            by_person=JIA, to_team="乙班", idempotency_key="east-h-3",
        )
        old = submit_receipt(
            self.east_grant_id,
            SubmitPayload(
                person=JIA, covered_zones=["东段-一号沟片区"], point_ids=["E-01"],
                log_time=EARLY_TIME, in_transit=True, findings="甲班在途：痕迹已清除",
            ),
        )["receipt"]
        new = submit_receipt(
            self.east_grant_id,
            SubmitPayload(
                person=YI, covered_zones=["东段-山脊片区"], point_ids=["E-02"],
                findings="乙班现场：威胁减轻，建议缩小",
            ),
        )["receipt"]
        return int(old["id"]), int(new["id"])

    def test_only_reviewed_valid_receipts_adoptable(self):
        old_id, new_id = self._prepare_east_receipts()
        # 待审阅回执不能采用
        with self.assertRaises(HTTPException):
            adopt_receipts(
                self.assessment_id,
                AdoptPayload(receipt_ids=[new_id], decision="缩小", issuer=ISSUER),
            )
        review_receipt(old_id, ReviewPayload(reviewer=REVIEWER, valid=True, note="在途材料可接续"))
        review_receipt(new_id, ReviewPayload(reviewer=REVIEWER, valid=True, note="现场核查有效"))
        # 驳回的回执不能采用
        rejected = submit_receipt(
            self.east_grant_id,
            SubmitPayload(
                person=YI, covered_zones=["东段-山脊片区"], point_ids=["E-02"],
                findings="重复上报", idempotency_key="dup-1",
            ),
        )["receipt"]
        review_receipt(int(rejected["id"]), ReviewPayload(reviewer=REVIEWER, valid=False, note="重复"))
        self.assertEqual(
            handover_service._require_receipt(int(rejected["id"]))["status"], RECEIPT_REJECTED)
        with self.assertRaises(HTTPException):
            adopt_receipts(
                self.assessment_id,
                AdoptPayload(receipt_ids=[int(rejected["id"])], decision="保留", issuer=ISSUER),
            )

        adoptable = handover_service.adoptable_receipts(self.assessment_id)
        self.assertEqual(sorted(r["id"] for r in adoptable["adoptable"]), sorted([old_id, new_id]))

    def test_adoption_updates_assessment_with_patrolled_scope_only(self):
        old_id, new_id = self._prepare_east_receipts()
        review_receipt(old_id, ReviewPayload(reviewer=REVIEWER, valid=True))
        review_receipt(new_id, ReviewPayload(reviewer=REVIEWER, valid=True))

        # 不能拿东段回执去调整没有实际巡护过的西段
        with self.assertRaises(HTTPException) as ctx:
            adopt_receipts(
                self.assessment_id,
                AdoptPayload(
                    receipt_ids=[old_id, new_id], decision="缩小",
                    issuer=ISSUER, evidence_scope=["西段-水源片区"],
                ),
            )
        self.assertIn("实际巡护", str(ctx.exception.detail))

        result = adopt_receipts(
            self.assessment_id,
            AdoptPayload(
                receipt_ids=[old_id, new_id], decision="缩小",
                issuer=ISSUER, evidence_scope=["东段-一号沟片区", "东段-山脊片区"],
            ),
        )
        self.assertTrue(result["ok"])
        assessment = store.find("threat_assessment", self.assessment_id)
        self.assertEqual(assessment["status"], "需更新")
        self.assertEqual(assessment["范围调整结论"], "缩小影响范围")
        self.assertEqual(
            sorted(assessment["实际巡护范围"]),
            ["东段-一号沟片区", "东段-山脊片区"],
        )
        self.assertIn(str(old_id), assessment["有效回执"])
        self.assertIn(str(new_id), assessment["有效回执"])
        basis = assessment["评估更新依据"][-1]
        self.assertIn("采用单#", basis)
        # 两份回执均标记已采用
        for rid in (old_id, new_id):
            self.assertTrue(handover_service._require_receipt(rid)["adopted"])

    def test_reviewing_old_receipt_shows_authorization_snapshot(self):
        old_id, _ = self._prepare_east_receipts()
        review_receipt(old_id, ReviewPayload(reviewer=REVIEWER, valid=True))
        receipt = handover_service.receipt_view(
            handover_service._require_receipt(old_id), role="审阅员")
        self.assertEqual(receipt["status"], RECEIPT_VALID)
        self.assertEqual(receipt["authorization_snapshot"]["授权人"], ISSUER)
        self.assertEqual(receipt["authorization_snapshot"]["有效范围"], ["东段"])
        self.assertEqual(receipt["reviewed_by"], REVIEWER)

    def test_issuer_final_choice_between_two_east_logs(self):
        """签发员最终可采用哪份东段日志：只采纳乙班现场有效日志时，甲班在途日志保持未采用。"""
        old_id, new_id = self._prepare_east_receipts()
        review_receipt(old_id, ReviewPayload(reviewer=REVIEWER, valid=True, note="可接续备查"))
        review_receipt(new_id, ReviewPayload(reviewer=REVIEWER, valid=True, note="作为缩小依据"))
        adopt_receipts(
            self.assessment_id,
            AdoptPayload(receipt_ids=[new_id], decision="缩小", issuer=ISSUER),
        )
        self.assertFalse(handover_service._require_receipt(old_id)["adopted"],
                         "甲班在途日志未被本轮采用，仍可备查接续")
        self.assertTrue(handover_service._require_receipt(new_id)["adopted"])
        # 之后仍可补采用甲班在途日志，旧材料能够接续
        adopt_receipts(
            self.assessment_id,
            AdoptPayload(receipt_ids=[old_id], decision="保留", issuer=ISSUER),
        )
        self.assertTrue(handover_service._require_receipt(old_id)["adopted"])

    def test_directory_matches_zone_constraints(self):
        self.assertEqual(TEAM_ZONES["甲班"], ["东段"])
        self.assertEqual(TEAM_ZONES["丙班"], ["西段"])
        self.assertEqual(PERSON_TEAM[JIA], "甲班")
        self.assertEqual(PERSON_TEAM[YI], "乙班")


def run_unittest() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_unittest())
