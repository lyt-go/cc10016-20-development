import { createRouter, createWebHistory } from 'vue-router'

import HandoverView from '@/views/HandoverView.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 固定路径需排在动态模块路径之前，否则会被 /:moduleKey 抢先匹配
    { path: '/handover', name: 'handover', component: HandoverView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
