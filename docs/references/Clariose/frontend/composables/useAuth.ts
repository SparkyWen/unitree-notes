/**
 * useAuth — minimal client-side session state. Mirrors the backend JWT.
 */
type SessionUser = {
  id: string;
  email: string;
  displayName: string | null;
  role: 'PATIENT' | 'CLINICIAN' | 'CARETAKER' | 'ADMIN';
};

export function useAuth() {
  const api = useApi();
  const user = useState<SessionUser | null>('clariose.user', () => null);
  const ready = useState<boolean>('clariose.user.ready', () => false);

  async function refresh() {
    if (!api.token.value) {
      user.value = null;
      ready.value = true;
      return;
    }
    try {
      user.value = await api.get<SessionUser>('/auth/me');
    } catch {
      user.value = null;
      api.token.value = null;
    } finally {
      ready.value = true;
    }
  }

  async function login(email: string, password: string) {
    const res = await api.post<{ token: string; user: SessionUser }>('/auth/login', { email, password });
    api.token.value = res.token;
    user.value = res.user;
  }

  async function register(payload: { email: string; password: string; displayName: string; role: SessionUser['role'] }) {
    const res = await api.post<{ token: string; user: SessionUser }>('/auth/register', payload);
    api.token.value = res.token;
    user.value = res.user;
  }

  function logout() {
    api.token.value = null;
    user.value = null;
    return navigateTo('/login');
  }

  return { user, ready, refresh, login, register, logout };
}
