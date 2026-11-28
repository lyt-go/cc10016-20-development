# 野生动物追踪与研究系统

生态学家、野外考察队员和数据分析师共同追踪野生动物活动轨迹，记录行为观测数据，分析种群迁徙规律后按研究周期汇总报告。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 物种登记 | `species_register` | 物种档案 | 物种名称、保护等级、分布区域 |
| 追踪设备 | `tracking_device` | 设备档案 | 设备编号、设备类型、佩戴对象 |
| 位置记录 | `location_record` | 位置数据 | 设备编号、经纬度、海拔高度 |
| 行为观测 | `behavior_observe` | 观测记录 | 观测对象、行为类型、起止时间 |
| 栖息地调查 | `habitat_survey` | 调查数据 | 调查区域、植被类型、水源距离 |
| 种群普查 | `population_census` | 普查记录 | 普查区域、目标物种、调查方法 |
| 迁徙路线 | `migration_track` | 迁徙路径 | 追踪个体、起点区域、途经区域 |
| 救护记录 | `rescue_record` | 救护档案 | 救护对象、发现地点、伤病情況 |
| 遗传样本 | `genetic_sample` | 样本档案 | 样本编号、来源个体、样本类型 |
| 巡护记录 | `patrol_record` | 巡护日志 | 巡护路线、巡护人员、发现情况 |
| 影像档案 | `photo_archive` | 影像记录 | 拍摄对象、拍摄地点、影像类型 |
| 研究成果 | `research_output` | 研究产出 | 成果标题、研究主题、作者团队 |
| 威胁评估 | `threat_assessment` | 评估报告 | 评估对象、威胁类别、威胁程度 |
| 装备管理 | `equipment_mgmt` | 装备档案 | 装备名称、装备类型、购入日期 |
| 公众宣教 | `public_education` | 宣教资料 | 资料名称、宣教主题、目标受众 |
| 合作项目 | `cooperation_project` | 项目档案 | 项目名称、合作机构、项目周期 |
| 数据分析 | `data_analysis` | 分析记录 | 分析主题、数据来源、分析方法 |
| 年度总结 | `annual_summary` | 总结报告 | 报告年份、覆盖物种、主要发现 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 巡护接办授权（敏感点位核查）

威胁评估签发后，按影响段下发「巡护接办授权」，独立领域包位于
`backend/app/handover/`，前端页面为「巡护接办」（路由 `/handover`）。

业务规则：

- **公开范围与点位分离**：授权单同时保存片区级 `public_scope`（公开处置范围）
  与 `precise_points`（敏感坐标）；非持有班组/非签发审阅视角只返回脱敏点位
  （编号保留、坐标为 `null`），越权错误回执也不含任何坐标。
- **片区限制**：班组与实际巡护片区在 `handover/store.py` 目录中绑定
  （甲/乙班与救护支援班负责东段，丙班负责西段）；跨班组领取、提交都按
  `TEAM_ZONES` 校验，越权直接拦截。
- **转交与幂等**：同片区班组间可转交（如甲班→乙班、甲班→救护支援班），
  凭 `idempotency_key` 保证重发只记一次交割；交割冻结授权人与有效范围快照。
- **在途日志接续**：转交后原现场人员进入在途补传名单，交割前产生的日志
  可由其补传（巡查时间须早于交割），交割后的新任务只认当前持有班组；
  `GET /api/handover/grants/{id}/intransit` 供接班员查询在途可上交人。
- **审阅与采用**：回执经审阅变为「有效/已驳回」，只有已审阅有效回执可供
  评估采用；采用时校验申请调整范围必须有实际巡护记录支撑，结果回写
  威胁评估申请（状态置为「需更新」，附采用依据、有效回执与实际巡护范围）。
- **可复核**：回执永久保留 `authorization_snapshot`，评估复核旧回执时
  能看到核查当时的授权人与有效范围。

主要接口（前缀 `/api/handover`）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/demo/reset` | 重建含东/西两段的演示评估与授权 |
| GET/POST | `/grants` | 查询/下发分段授权 |
| POST | `/grants/{id}/claim` | 按片区校验领取 |
| POST | `/grants/{id}/transfer` | 转交（幂等键防重复交割） |
| GET | `/grants/{id}/intransit` | 查询在途日志可上交人员 |
| POST | `/grants/{id}/receipts` | 提交巡护日志（支持在途补传） |
| POST | `/receipts/{id}/review` | 审阅有效/驳回 |
| GET | `/assessments/{id}/adoptable` | 可供采用的有效回执 |
| POST | `/assessments/{id}/adopt` | 采用回执并回写评估申请 |

测试：`backend/.venv/bin/python backend/tests/test_handover.py`（15 个用例，
覆盖领取/转交/在途接续/审阅/采用全链路与越权脱敏）。

领域：应用开发
子方向：web前端/全栈开发
