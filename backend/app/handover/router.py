"""巡护接办授权 API。

路由层只做参数解析与 HTTP 状态映射，授权、片区限制、脱敏、状态流转
全部位于 app.handover.service。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.handover.service import ROLE_REVIEWER, HandoverError, handover_service

router = APIRouter(prefix="/api/handover", tags=["巡护接办授权"])


class PointIn(BaseModel):
    point_id: str
    name: str
    lat: float
    lng: float


class SegmentIn(BaseModel):
    segment: str
    public_scope: str = ""
    points: list[PointIn] = Field(default_factory=list)


class IssuePayload(BaseModel):
    assessment_id: int
    segments: list[SegmentIn]
    issued_by: str


class ClaimPayload(BaseModel):
    person: str


class TransferPayload(BaseModel):
    by_person: str
    to_team: str
    idempotency_key: str


class SubmitPayload(BaseModel):
    person: str
    covered_zones: list[str]
    point_ids: list[str] = Field(default_factory=list)
    log_time: str | None = None
    in_transit: bool = False
    findings: str = ""
    idempotency_key: str | None = None


class ReviewPayload(BaseModel):
    reviewer: str
    valid: bool
    note: str = ""


class AdoptPayload(BaseModel):
    receipt_ids: list[int]
    decision: str
    issuer: str
    evidence_scope: list[str] | None = None


class ResetPayload(BaseModel):
    issued_by: str = "签发员-林工"


def _fail(exc: HandoverError) -> HTTPException:
    # 业务错误消息只含片区/编号级信息，精确点位永远不会出现在错误回执中
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/roster")
def roster() -> dict[str, Any]:
    return handover_service.roster()


@router.post("/demo/reset")
def reset_demo(payload: ResetPayload) -> dict[str, Any]:
    return handover_service.reset_demo(issued_by=payload.issued_by)


@router.post("/grants")
def issue_grants(payload: IssuePayload) -> dict[str, Any]:
    try:
        segments = [
            {
                "segment": item.segment,
                "public_scope": item.public_scope,
                "points": [p.model_dump() for p in item.points],
            }
            for item in payload.segments
        ]
        grants = handover_service.issue_grants(
            payload.assessment_id, segments, issued_by=payload.issued_by)
    except HandoverError as exc:
        raise _fail(exc)
    return {"ok": True, "grants": [handover_service.public_view(g) for g in grants]}


@router.get("/grants")
def list_grants(
    assessment_id: int | None = None,
    team: str | None = None,
    role: str = "",
) -> dict[str, Any]:
    return {"items": handover_service.list_grants(
        assessment_id=assessment_id, team=team, role=role)}


@router.get("/grants/{grant_id}")
def get_grant(grant_id: int, team: str | None = None, role: str = "") -> dict[str, Any]:
    try:
        grant = handover_service._require_grant(grant_id)
    except HandoverError as exc:
        raise _fail(exc)
    return handover_service.grant_view(grant, team=team, role=role)


@router.post("/grants/{grant_id}/claim")
def claim_grant(grant_id: int, payload: ClaimPayload) -> dict[str, Any]:
    try:
        grant = handover_service.claim_grant(grant_id, payload.person)
    except HandoverError as exc:
        raise _fail(exc)
    team = handover_service._team_of(payload.person)
    return {"ok": True, "message": f"{team}已领取{grant['segment']}巡护任务",
            "grant": handover_service.grant_view(grant, team=team)}


@router.post("/grants/{grant_id}/transfer")
def transfer_grant(grant_id: int, payload: TransferPayload) -> dict[str, Any]:
    try:
        event = handover_service.transfer_grant(
            grant_id,
            by_person=payload.by_person,
            to_team=payload.to_team,
            idempotency_key=payload.idempotency_key,
        )
    except HandoverError as exc:
        raise _fail(exc)
    return {"ok": True, "event": event}


@router.get("/grants/{grant_id}/intransit")
def intransit_candidates(grant_id: int) -> dict[str, Any]:
    try:
        return handover_service.intransit_candidates(grant_id)
    except HandoverError as exc:
        raise _fail(exc)


@router.post("/grants/{grant_id}/receipts")
def submit_receipt(grant_id: int, payload: SubmitPayload) -> dict[str, Any]:
    try:
        receipt = handover_service.submit_receipt(
            grant_id,
            person=payload.person,
            covered_zones=payload.covered_zones,
            point_ids=payload.point_ids,
            log_time=payload.log_time,
            in_transit=payload.in_transit,
            findings=payload.findings,
            idempotency_key=payload.idempotency_key,
        )
    except HandoverError as exc:
        raise _fail(exc)
    team = handover_service._team_of(payload.person)
    view = handover_service.receipt_view(receipt, team=team)
    return {"ok": True, "message": "巡护日志已提交，等待审阅", "receipt": view}


@router.get("/receipts")
def list_receipts(
    grant_id: int | None = None,
    team: str | None = None,
    role: str = "",
) -> dict[str, Any]:
    return {"items": handover_service.list_receipts(
        grant_id=grant_id, team=team, role=role)}


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: int, team: str | None = None, role: str = "") -> dict[str, Any]:
    try:
        receipt = handover_service._require_receipt(receipt_id)
    except HandoverError as exc:
        raise _fail(exc)
    return handover_service.receipt_view(receipt, team=team, role=role)


@router.post("/receipts/{receipt_id}/review")
def review_receipt(receipt_id: int, payload: ReviewPayload) -> dict[str, Any]:
    try:
        receipt = handover_service.review_receipt(
            receipt_id, reviewer=payload.reviewer, valid=payload.valid, note=payload.note)
    except HandoverError as exc:
        raise _fail(exc)
    return {"ok": True, "receipt": handover_service.receipt_view(
        receipt, role=ROLE_REVIEWER)}


@router.get("/assessments/{assessment_id}/adoptable")
def adoptable_receipts(assessment_id: int) -> dict[str, Any]:
    return handover_service.adoptable_receipts(assessment_id)


@router.post("/assessments/{assessment_id}/adopt")
def adopt_receipts(assessment_id: int, payload: AdoptPayload) -> dict[str, Any]:
    try:
        result = handover_service.adopt_receipts(
            assessment_id,
            receipt_ids=payload.receipt_ids,
            decision=payload.decision,
            issuer=payload.issuer,
            evidence_scope=payload.evidence_scope,
        )
    except HandoverError as exc:
        raise _fail(exc)
    result["ok"] = True
    return result


@router.get("/transfers")
def list_transfers(grant_id: int | None = None) -> dict[str, Any]:
    return {"items": handover_service.list_transfers(grant_id)}
