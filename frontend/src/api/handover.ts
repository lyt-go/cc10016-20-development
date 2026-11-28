/** 巡护接办授权 API：授权单、交割、巡护回执、审阅与评估采用。 */
import { request } from './client'

export type GrantView = {
  id: number
  assessment_id: number
  segment: string
  public_scope: string
  sensitive_point_count: number
  status: string
  current_team: string | null
  current_holder: string | null
  issued_by: string
  issued_at: string
  precise_points: { point_id: string; name: string; lat: number | null; lng: number | null }[]
  claims: { team: string; person: string; at: string }[]
  transfer_ids: number[]
}

export type ReceiptView = {
  id: number
  grant_id: number
  assessment_id: number
  segment: string
  kind: string
  submitter: string
  team: string
  covered_zones: string[]
  precise_points: { point_id: string; name: string; lat: number | null; lng: number | null }[]
  log_time: string
  findings: string
  status: string
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string
  adopted: boolean
  authorization_snapshot: Record<string, unknown>
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  const payload = await response.json()
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? payload.detail : '请求被业务规则拒绝'
    throw new Error(detail)
  }
  return payload as T
}

export function resetDemo(issuedBy = '签发员-林工') {
  return call<{ assessment_id: number; grants: GrantView[] }>('/api/handover/demo/reset', {
    method: 'POST',
    body: JSON.stringify({ issued_by: issuedBy }),
  })
}

export function fetchRoster() {
  return call<{ team_zones: Record<string, string[]>; person_team: Record<string, string> }>(
    '/api/handover/roster',
  )
}

export function fetchGrants(team?: string, role = '') {
  const params = new URLSearchParams()
  if (team) params.set('team', team)
  if (role) params.set('role', role)
  const qs = params.toString()
  return call<{ items: GrantView[] }>(`/api/handover/grants${qs ? `?${qs}` : ''}`)
}

export function fetchGrant(id: number, team?: string, role = '') {
  const params = new URLSearchParams()
  if (team) params.set('team', team)
  if (role) params.set('role', role)
  const qs = params.toString()
  return call<GrantView>(`/api/handover/grants/${id}${qs ? `?${qs}` : ''}`)
}

export function claimGrant(id: number, person: string) {
  return call<{ ok: boolean; message: string; grant: GrantView }>(
    `/api/handover/grants/${id}/claim`,
    { method: 'POST', body: JSON.stringify({ person }) },
  )
}

export function transferGrant(id: number, byPerson: string, toTeam: string, idempotencyKey: string) {
  return call<{ ok: boolean; event: Record<string, unknown> }>(
    `/api/handover/grants/${id}/transfer`,
    {
      method: 'POST',
      body: JSON.stringify({
        by_person: byPerson,
        to_team: toTeam,
        idempotency_key: idempotencyKey,
      }),
    },
  )
}

export function fetchIntransit(id: number) {
  return call<{
    grant_id: number
    segment: string
    current_team: string
    intransit_submitters: { person: string; team: string; handover_at: string; remaining: boolean }[]
  }>(`/api/handover/grants/${id}/intransit`)
}

export function submitReceipt(
  id: number,
  payload: {
    person: string
    covered_zones: string[]
    point_ids: string[]
    log_time?: string
    in_transit?: boolean
    findings?: string
    idempotency_key?: string
  },
) {
  return call<{ ok: boolean; message: string; receipt: ReceiptView }>(
    `/api/handover/grants/${id}/receipts`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export function fetchReceipts(role = '') {
  const qs = role ? `?role=${encodeURIComponent(role)}` : ''
  return call<{ items: ReceiptView[] }>(`/api/handover/receipts${qs}`)
}

export function reviewReceipt(id: number, reviewer: string, valid: boolean, note: string) {
  return call<{ ok: boolean; receipt: ReceiptView }>(`/api/handover/receipts/${id}/review`, {
    method: 'POST',
    body: JSON.stringify({ reviewer, valid, note }),
  })
}

export function fetchAdoptable(assessmentId: number) {
  return call<{
    assessment_id: number
    adoptable: ReceiptView[]
    all_receipts: Record<string, unknown>[]
  }>(`/api/handover/assessments/${assessmentId}/adoptable`)
}

export function adoptReceipts(
  assessmentId: number,
  payload: { receipt_ids: number[]; decision: string; issuer: string; evidence_scope?: string[] },
) {
  return call<{ ok: boolean; assessment_status: string }>(
    `/api/handover/assessments/${assessmentId}/adopt`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export function fetchTransfers(grantId?: number) {
  const qs = grantId ? `?grant_id=${grantId}` : ''
  return call<{ items: Record<string, unknown>[] }>(`/api/handover/transfers${qs}`)
}
