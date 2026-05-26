/**
 * Boot-time session hydration. If a cookie is present, kick off /auth/me
 * so SiteHeader / page guards see the right `user.value` quickly.
 *
 * IMPORTANT: We must NOT `await` here. This is a `.client` plugin, so it
 * never runs during SSR — the server always renders with user=null. If
 * we awaited the refresh before mount, the client's first render would
 * use the freshly-fetched user, which differs from the SSR HTML, and
 * Vue would log "Hydration completed but contains mismatches" on every
 * SSR'd route (/dashboard, /reminders, /summary, /carenote shells).
 *
 * Firing without await means: mount sees user=null (matches SSR), then
 * the refresh resolves a moment later and Vue re-renders the header
 * reactively — no hydration mismatch. SiteHeader.vue still has its own
 * onMounted fallback for the case where the cookie was set after the
 * plugin had already returned.
 */
export default defineNuxtPlugin(() => {
  const auth = useAuth();
  const api = useApi();
  if (api.token.value && !auth.user.value) {
    void auth.refresh();
  }
});
