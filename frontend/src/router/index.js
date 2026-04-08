import { createRouter, createWebHistory } from 'vue-router'

import { getWorkspaceRoute, isAdmin, isAuthenticated } from '../services/api'
import DashboardView from '../views/admin/DashboardView.vue'
import LoginView from '../views/admin/LoginView.vue'
import SkillDetailView from '../views/admin/SkillDetailView.vue'
import SkillFormView from '../views/admin/SkillFormView.vue'
import UserManagementView from '../views/admin/UserManagementView.vue'
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
    { path: '/login', name: 'login', component: LoginView },
    { path: '/workspace', name: 'workspace-dashboard', component: DashboardView, meta: { requiresAuth: true } },
    {
      path: '/workspace/skills/new',
      name: 'workspace-skill-create',
      component: SkillFormView,
      meta: { requiresAuth: true },
    },
    {
      path: '/workspace/skills/:name/edit',
      name: 'workspace-skill-edit',
      component: SkillFormView,
      props: true,
      meta: { requiresAuth: true },
    },
    {
      path: '/workspace/skills/:name',
      name: 'workspace-skill-detail',
      component: SkillDetailView,
      props: true,
      meta: { requiresAuth: true },
    },
    {
      path: '/workspace/users',
      name: 'workspace-users',
      component: UserManagementView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    { path: '/admin/login', redirect: '/login' },
    { path: '/admin', redirect: '/workspace' },
    { path: '/admin/skills/new', redirect: '/workspace/skills/new' },
    { path: '/admin/skills/:name/edit', redirect: (to) => `/workspace/skills/${to.params.name}/edit` },
    { path: '/admin/skills/:name', redirect: (to) => `/workspace/skills/${to.params.name}` },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !isAuthenticated()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !isAdmin()) {
    return { path: getWorkspaceRoute() }
  }
  if (to.name === 'login' && isAuthenticated()) {
    return { path: getWorkspaceRoute() }
  }
  return true
})

export default router
