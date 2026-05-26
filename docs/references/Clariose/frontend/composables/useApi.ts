/**
 * useApi — thin wrapper around $fetch that targets the public API base.
 * Centralises base URL, auth header injection, and a tiny error normaliser.
 */
import type { FetchOptions } from 'ofetch';

export function useApi() {
  const config = useRuntimeConfig();
  const token = useCookie<string | null>('clariose_token', {
    sameSite: 'lax',
    secure: !import.meta.dev,
    maxAge: 60 * 60 * 24 * 7,
    path: '/',
  });

  async function request<T>(path: string, opts: FetchOptions = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...((opts.headers as Record<string, string>) || {}),
    };
    if (token.value) headers.Authorization = `Bearer ${token.value}`;

    try {
      return await $fetch<T>(`${config.public.apiBase}${path}`, {
        ...opts,
        headers,
      } as any);
    } catch (err: any) {
      if (err?.response?.status === 401 && path !== '/auth/login' && path !== '/auth/register') {
        token.value = null;
        if (import.meta.client) {
          const route = useRoute();
          await navigateTo({ path: '/login', query: { redirect: route.fullPath, expired: '1' } });
        }
      }
      throw err;
    }
  }

  return {
    get:    <T>(path: string, opts?: FetchOptions) => request<T>(path, { ...opts, method: 'GET' }),
    post:   <T>(path: string, body?: unknown, opts?: FetchOptions) =>
      request<T>(path, { ...opts, method: 'POST', body: body as any }),
    patch:  <T>(path: string, body?: unknown, opts?: FetchOptions) =>
      request<T>(path, { ...opts, method: 'PATCH', body: body as any }),
    delete: <T>(path: string, opts?: FetchOptions) => request<T>(path, { ...opts, method: 'DELETE' }),
    token,
  };
}
