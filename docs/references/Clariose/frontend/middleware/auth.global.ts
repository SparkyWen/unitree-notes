/**
 * Global route guard. Anything under the "app" surface requires a JWT cookie.
 * Public surface: marketing landing, /login, /register.
 *
 * We deliberately gate on cookie presence (cheap, SSR-safe). The real check is
 * server-side — the backend rejects bad/expired tokens with 401. If `/auth/me`
 * later fails, `useAuth.refresh()` clears the cookie and SiteHeader re-renders
 * as logged-out.
 */
const PROTECTED_PREFIXES = [
  '/dashboard',
  '/summary',
  '/reminders',
  '/carenote',
  '/recall',
];

const PUBLIC_ONLY = ['/login', '/register'];

export default defineNuxtRouteMiddleware((to) => {
  const token = useCookie<string | null>('clariose_token');
  const isAuthed = !!token.value;

  const requiresAuth = PROTECTED_PREFIXES.some(
    (p) => to.path === p || to.path.startsWith(`${p}/`),
  );
  const isPublicOnly = PUBLIC_ONLY.includes(to.path);

  if (requiresAuth && !isAuthed) {
    return navigateTo({
      path: '/login',
      query: { redirect: to.fullPath },
    });
  }

  if (isPublicOnly && isAuthed) {
    return navigateTo('/dashboard');
  }
});
