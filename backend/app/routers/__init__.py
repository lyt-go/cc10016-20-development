"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.handover import router as handover
from app.routers import cross_module, resource

# handover 含 /api/handover/transfers 等固定路径，必须先于通用资源路由
# （/api/{module}/{entry_id}）注册，否则固定路径会被动态路径抢先匹配。
ROUTERS = [handover, resource, cross_module]
