export const getToken = (): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem('ttm_token') : null;

export const setAuth = (token: string, userId: string, username: string, timezone: string) => {
  localStorage.setItem('ttm_token', token);
  localStorage.setItem('ttm_user_id', userId);
  localStorage.setItem('ttm_username', username);
  localStorage.setItem('ttm_timezone', timezone);
};

export const clearAuth = () => {
  localStorage.removeItem('ttm_token');
  localStorage.removeItem('ttm_user_id');
  localStorage.removeItem('ttm_username');
  localStorage.removeItem('ttm_timezone');
};

export const getUserId = (): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem('ttm_user_id') : null;

export const getUsername = (): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem('ttm_username') : null;

/** The signed-in user's profile timezone (IANA), falling back to the browser's. */
export const getTimezone = (): string =>
  (typeof window !== 'undefined' && localStorage.getItem('ttm_timezone')) ||
  Intl.DateTimeFormat().resolvedOptions().timeZone;

export const isAuthenticated = (): boolean => !!getToken();
