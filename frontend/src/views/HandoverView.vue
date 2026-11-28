<template>
  <section class="page handover-page">
    <header class="page-head">
      <div>
        <h2>巡护接办授权</h2>
        <p class="page-desc">
          威胁评估签发后按影响段下发巡护接办授权：公开处置范围与现场敏感点位分离，
          跨班组领取/提交受实际巡护片区限制，仅已审阅有效回执可回写评估。
        </p>
      </div>
      <div class="page-actions">
        <label class="filter-item">
          <span>当前班组视角</span>
          <select v-model="team" data-testid="team-select" @change="reload">
            <option value="">（公开视角）</option>
            <option v-for="name in teams" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <button class="btn primary" type="button" data-testid="reset-demo" @click="resetDemoData">
          重建演示数据
        </button>
      </div>
    </header>

    <p v-if="message" class="status-legend" :class="{ 'error-text': hasError }">{{ message }}</p>

    <article class="handover-card">
      <h3>① 巡护接办授权单（按影响段）</h3>
      <p class="muted">
        公开处置范围为片区级描述；精确点位仅当前持有班组与签发/审阅岗位可见，其他视角自动脱敏。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>授权单</th><th>影响段</th><th>公开处置范围</th><th>状态</th>
            <th>持有班组</th><th>敏感点位（按视角）</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="grant in grants" :key="grant.id" :data-testid="`grant-${grant.id}`">
            <td>#{{ grant.id }}</td>
            <td>{{ grant.segment }}</td>
            <td class="scope-cell">{{ grant.public_scope }}</td>
            <td>{{ grant.status }}</td>
            <td>{{ grant.current_team ?? '—' }}</td>
            <td>
              <span v-for="p in grant.precise_points" :key="p.point_id" class="point-chip"
                    :data-masked="p.lat === null">
                {{ p.point_id }}<template v-if="p.lat !== null">：{{ p.lat }}, {{ p.lng }}</template>
                <template v-else>：无权查看</template>
              </span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openClaim(grant)">领取</button>
              <button class="link" type="button" @click="openTransfer(grant)">转交</button>
              <button class="link" type="button" @click="openIntransit(grant)">在途交接</button>
              <button class="link" type="button" @click="openSubmit(grant)">提交日志</button>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <article class="handover-card">
      <h3>② 巡护回执与审阅</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>回执</th><th>影响段</th><th>类型</th><th>班组/人员</th><th>实际巡护范围</th>
            <th>点位（按视角）</th><th>状态</th><th>已采用</th><th>授权快照</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in receipts" :key="r.id" :data-testid="`receipt-${r.id}`">
            <td>#{{ r.id }}</td>
            <td>{{ r.segment }}</td>
            <td>{{ r.kind }}</td>
            <td>{{ r.team }} / {{ r.submitter }}</td>
            <td>{{ r.covered_zones.join('、') }}</td>
            <td>
              <span v-for="p in r.precise_points" :key="p.point_id" class="point-chip"
                    :data-masked="p.lat === null">
                <template v-if="p.lat !== null">{{ p.point_id }}：{{ p.lat }}, {{ p.lng }}</template>
                <template v-else>{{ p.point_id }}：无权查看</template>
              </span>
            </td>
            <td>{{ r.status }}</td>
            <td>{{ r.adopted ? '是' : '否' }}</td>
            <td class="snapshot-cell">
              授权人：{{ String(snapshotOf(r).授权人 ?? '—') }}；
              有效范围：{{ (snapshotOf(r).有效范围 as string[] | undefined)?.join('、') ?? '—' }}
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openReview(r, true)">审阅有效</button>
              <button class="link" type="button" @click="openReview(r, false)">驳回</button>
            </td>
          </tr>
          <tr v-if="!receipts.length">
            <td colspan="10" class="empty-state">暂无巡护回执</td>
          </tr>
        </tbody>
      </table>
    </article>

    <article class="handover-card">
      <h3>③ 评估采用（仅已审阅有效回执，且只能调整实际巡护过的范围）</h3>
      <div class="adopt-bar">
        <label><span>评估单</span><input v-model.number="assessmentId" type="number" data-testid="adopt-aid" /></label>
        <label><span>回执编号（逗号分隔）</span><input v-model="adoptReceiptIds" data-testid="adopt-rids" /></label>
        <label><span>结论</span>
          <select v-model="adoptDecision">
            <option value="缩小">缩小影响范围</option>
            <option value="保留">保留影响范围</option>
          </select>
        </label>
        <label><span>申请调整范围（逗号分隔，留空取实际巡护范围）</span>
          <input v-model="adoptScope" placeholder="如：东段-一号沟片区" />
        </label>
        <button class="btn primary" type="button" data-testid="adopt-submit" @click="submitAdopt">回写评估申请</button>
        <button class="btn" type="button" @click="loadAdoptable">查看可采用回执</button>
      </div>
      <ul v-if="adoptableIds.length" class="adopt-list">
        <li v-for="id in adoptableIds" :key="id">可采用有效回执 #{{ id }}</li>
      </ul>
    </article>

    <!-- 领取弹窗 -->
    <div v-if="claimTarget" class="modal-backdrop" @click.self="claimTarget = null">
      <form class="modal" @submit.prevent="submitClaim">
        <h3>领取授权单 #{{ claimTarget.id }}（{{ claimTarget.segment }}）</h3>
        <label class="create-field"><span>领取人员</span>
          <select v-model="claimPerson" required>
            <option value="" disabled>请选择</option>
            <option v-for="(t, p) in roster.person_team" :key="p" :value="p">{{ p }}（{{ t }}）</option>
          </select>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="claimTarget = null">取消</button>
          <button class="btn primary" type="submit">确认领取</button>
        </div>
      </form>
    </div>

    <!-- 转交弹窗 -->
    <div v-if="transferTarget" class="modal-backdrop" @click.self="transferTarget = null">
      <form class="modal" @submit.prevent="submitTransfer">
        <h3>转交授权单 #{{ transferTarget.id }}（{{ transferTarget.segment }}）</h3>
        <p class="muted">重发同一请求不会重复记账：系统按幂等键只记一次交割。</p>
        <label class="create-field"><span>转交人（当前持有班组）</span>
          <input v-model="transferBy" required placeholder="如：甲班-赵巡" />
        </label>
        <label class="create-field"><span>接办班组</span>
          <select v-model="transferTo" required>
            <option value="" disabled>请选择</option>
            <option v-for="name in teams" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label class="create-field"><span>幂等键</span>
          <input v-model="transferKey" required placeholder="如：east-jia-yi-001" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="transferTarget = null">取消</button>
          <button class="btn primary" type="submit">确认转交</button>
        </div>
      </form>
    </div>

    <!-- 在途交接弹窗 -->
    <div v-if="intransitTarget" class="modal-backdrop" @click.self="intransitTarget = null">
      <div class="modal">
        <h3>在途日志交接（授权单 #{{ intransitTarget.id }}）</h3>
        <p>当前持有班组：{{ intransitInfo?.current_team ?? '—' }}</p>
        <p class="muted">下列原现场人员在交割前产生的在途日志仍可补传，交割后的新任务只认当前持有班组：</p>
        <ul>
          <li v-for="c in intransitInfo?.intransit_submitters ?? []" :key="c.person">
            {{ c.person }}（{{ c.team }}），交割时间 {{ c.handover_at }}，
            剩余补传资格：{{ c.remaining ? '有' : '已用' }}
          </li>
          <li v-if="!(intransitInfo?.intransit_submitters.length)">暂无在途补传人员</li>
        </ul>
        <div class="page-actions"><button class="btn primary" type="button" @click="intransitTarget = null">知道了</button></div>
      </div>
    </div>

    <!-- 提交日志弹窗 -->
    <div v-if="submitTarget" class="modal-backdrop" @click.self="submitTarget = null">
      <form class="modal" @submit.prevent="submitReceiptForm">
        <h3>提交巡护日志（授权单 #{{ submitTarget.id }} · {{ submitTarget.segment }}）</h3>
        <label class="create-field"><span>提交人员</span>
          <select v-model="formPerson" required>
            <option value="" disabled>请选择</option>
            <option v-for="(t, p) in roster.person_team" :key="p" :value="p">{{ p }}（{{ t }}）</option>
          </select>
        </label>
        <label class="create-field"><span>实际巡护范围（逗号分隔）</span>
          <input v-model="formZones" required placeholder="如：东段-一号沟片区" />
        </label>
        <label class="create-field"><span>核查点位（逗号分隔）</span>
          <input v-model="formPoints" placeholder="如：E-01,E-02" />
        </label>
        <label class="create-field"><span>发现情况</span><textarea v-model="formFindings" rows="2"></textarea></label>
        <label class="create-field"><span>巡查时间（在途补传时必填，须早于交割）</span>
          <input v-model="formLogTime" placeholder="2026-01-01T08:00:00" />
        </label>
        <label class="create-field"><span>日志类型</span>
          <select v-model="formInTransit">
            <option :value="false">现场提交（当前持有班组）</option>
            <option :value="true">在途补传（交割前已产生）</option>
          </select>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="submitTarget = null">取消</button>
          <button class="btn primary" type="submit">提交日志</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  adoptReceipts,
  claimGrant,
  fetchAdoptable,
  fetchGrants,
  fetchIntransit,
  fetchReceipts,
  fetchRoster,
  resetDemo,
  reviewReceipt,
  submitReceipt,
  transferGrant,
  type GrantView,
  type ReceiptView,
} from '@/api/handover'

const REVIEWER_ROLE = '审阅员'

const team = ref('')
const grants = ref<GrantView[]>([])
const receipts = ref<ReceiptView[]>([])
const roster = ref<{ team_zones: Record<string, string[]>; person_team: Record<string, string> }>({
  team_zones: {},
  person_team: {},
})
const message = ref('')
const hasError = ref(false)

const teams = computed(() => Object.keys(roster.value.team_zones))

function notify(text: string, error = false) {
  message.value = text
  hasError.value = error
}

async function reload() {
  try {
    const [grantPage, receiptPage] = await Promise.all([
      fetchGrants(team.value || undefined),
      fetchReceipts(),
    ])
    grants.value = grantPage.items
    receipts.value = receiptPage.items
  } catch (error) {
    notify(error instanceof Error ? error.message : '数据加载失败', true)
  }
}

async function resetDemoData() {
  try {
    const demo = await resetDemo()
    assessmentId.value = demo.assessment_id
    notify(`演示数据已重建：威胁评估 #${demo.assessment_id}，含 ${demo.grants.length} 段授权`)
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '重建失败', true)
  }
}

// 领取
const claimTarget = ref<GrantView | null>(null)
const claimPerson = ref('')
function openClaim(grant: GrantView) {
  claimTarget.value = grant
  claimPerson.value = ''
}
async function submitClaim() {
  if (!claimTarget.value) return
  try {
    const result = await claimGrant(claimTarget.value.id, claimPerson.value)
    notify(result.message)
    claimTarget.value = null
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '领取失败', true)
  }
}

// 转交
const transferTarget = ref<GrantView | null>(null)
const transferBy = ref('')
const transferTo = ref('')
const transferKey = ref('')
function openTransfer(grant: GrantView) {
  transferTarget.value = grant
  transferBy.value = grant.current_holder ?? ''
  transferTo.value = ''
  transferKey.value = `${grant.segment}-${Date.now()}`
}
async function submitTransfer() {
  if (!transferTarget.value) return
  try {
    const result = await transferGrant(
      transferTarget.value.id, transferBy.value, transferTo.value, transferKey.value,
    )
    notify(`交割已登记 #${(result.event as { id: number }).id}（重发同幂等键不会重复记账）`)
    transferTarget.value = null
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '转交失败', true)
  }
}

// 在途交接
const intransitTarget = ref<GrantView | null>(null)
const intransitInfo = ref<Awaited<ReturnType<typeof fetchIntransit>> | null>(null)
async function openIntransit(grant: GrantView) {
  intransitTarget.value = grant
  try {
    intransitInfo.value = await fetchIntransit(grant.id)
  } catch (error) {
    notify(error instanceof Error ? error.message : '在途信息读取失败', true)
  }
}

// 提交日志
const submitTarget = ref<GrantView | null>(null)
const formPerson = ref('')
const formZones = ref('')
const formPoints = ref('')
const formFindings = ref('')
const formLogTime = ref('')
const formInTransit = ref(false)
function openSubmit(grant: GrantView) {
  submitTarget.value = grant
  formPerson.value = ''
  formZones.value = `${grant.segment}-`
  formPoints.value = ''
  formFindings.value = ''
  formLogTime.value = ''
  formInTransit.value = false
}
async function submitReceiptForm() {
  if (!submitTarget.value) return
  try {
    const result = await submitReceipt(submitTarget.value.id, {
      person: formPerson.value,
      covered_zones: formZones.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
      point_ids: formPoints.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
      findings: formFindings.value,
      log_time: formLogTime.value || undefined,
      in_transit: formInTransit.value,
    })
    notify(result.message)
    submitTarget.value = null
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '提交失败', true)
  }
}

// 审阅
async function openReview(receipt: ReceiptView, valid: boolean) {
  const reviewer = window.prompt('审阅人员', '审阅员-秦工')
  if (!reviewer) return
  const note = window.prompt(valid ? '审阅意见（有效）' : '驳回原因', '') ?? ''
  try {
    await reviewReceipt(receipt.id, reviewer, valid, note)
    notify(`回执 #${receipt.id} 已${valid ? '审阅为有效' : '驳回'}`)
    await reload()
  } catch (error) {
    notify(error instanceof Error ? error.message : '审阅失败', true)
  }
}

// 评估采用
const assessmentId = ref<number | null>(null)
const adoptReceiptIds = ref('')
const adoptDecision = ref('缩小')
const adoptScope = ref('')
const adoptableIds = ref<number[]>([])

function snapshotOf(receipt: ReceiptView): Record<string, unknown> {
  return receipt.authorization_snapshot ?? {}
}

async function loadAdoptable() {
  if (!assessmentId.value) {
    notify('请先填写评估单编号', true)
    return
  }
  try {
    const data = await fetchAdoptable(assessmentId.value)
    adoptableIds.value = data.adoptable.map((r) => r.id)
    notify(`评估 #${assessmentId.value} 下有 ${adoptableIds.value.length} 份已审阅有效回执可供采用`)
  } catch (error) {
    notify(error instanceof Error ? error.message : '可采用回执读取失败', true)
  }
}

async function submitAdopt() {
  if (!assessmentId.value) {
    notify('请先填写评估单编号', true)
    return
  }
  const ids = adoptReceiptIds.value.split(/[，,]/).map((s) => Number(s.trim())).filter(Boolean)
  const scopes = adoptScope.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean)
  try {
    const result = await adoptReceipts(assessmentId.value, {
      receipt_ids: ids,
      decision: adoptDecision.value,
      issuer: '签发员-林工',
      evidence_scope: scopes.length ? scopes : undefined,
    })
    notify(`评估申请已回写，当前状态：${result.assessment_status}`)
    await reload()
    await loadAdoptable()
  } catch (error) {
    notify(error instanceof Error ? error.message : '评估采用失败', true)
  }
}

onMounted(async () => {
  roster.value = await fetchRoster()
  const demo = await resetDemo()
  assessmentId.value = demo.assessment_id
  await reload()
})
</script>

<style scoped>
.handover-card {
  background: #fff;
  border: 1px solid #e3e7ee;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 18px;
}
.muted { color: #6b7280; font-size: 13px; }
.scope-cell { max-width: 280px; }
.snapshot-cell { font-size: 12px; color: #374151; }
.point-chip {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: #e8f3ff;
  font-size: 12px;
}
.point-chip[data-masked='true'] { background: #f3f4f6; color: #9ca3af; }
.adopt-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.adopt-bar label { display: flex; flex-direction: column; font-size: 13px; gap: 4px; }
.adopt-bar input, .adopt-bar select { min-width: 180px; }
.adopt-list { margin-top: 10px; color: #0f766e; }
</style>
