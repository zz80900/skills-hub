import { createRouter, createWebHistory } from 'vue-router'

import { getToken } from '../services/api'
import DashboardView from '../views/admin/DashboardView.vue'
import LoginView from '../views/admin/LoginView.vue'
import SkillDetailView from '../views/admin/SkillDetailView.vue'
import SkillFormView from '../views/admin/SkillFormView.vue'
import HomeView from '../views/public/HomeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    {
      path: '/skills/:name',
      name: 'skill-detail',
      redirect: (to) => ({ name: 'home', query: { ...to.query, skill: to.params.name } }),
    },
    { path: '/admin/login', name: 'admin-login', component: LoginView },
    { path: '/admin', name: 'admin-dashboard', component: DashboardView, meta: { requiresAuth: true } },
    { path: '/admin/skills/new', name: 'admin-skill-create', component: SkillFormView, meta: { requiresAuth: true } },
    { path: '/admin/skills/:name/edit', name: 'admin-skill-edit', component: SkillFormView, props: true, meta: { requiresAuth: true } },
    { path: '/admin/skills/:name', name: 'admin-skill-detail', component: SkillDetailView, props: true, meta: { requiresAuth: true } },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !getToken()) {
    return { name: 'admin-login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'admin-login' && getToken()) {
    return { name: 'admin-dashboard' }
  }
  return true
})

export default router
