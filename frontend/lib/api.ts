import { getToken, clearAuth } from './auth';

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8080';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearAuth();
    window.location.href = '/auth/signin';
    throw new ApiError(401, 'Unauthorized');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- Feed types (the unified stream) ---

export interface SessionMeta {
  status: string;
  purpose: string | null;
  proposed_start: string | null;
  proposed_end: string | null;
  participants: string[];   // the OTHER participants (excludes the viewer)
  my_approval_status: string;
  updated_at: string;
}

export interface ChatItem {
  kind: 'chat';
  id: string;
  role: 'user' | 'agent';
  content: string;
  session_id: string | null;
  participants: string[];   // the OTHER people in the tagged meeting (for the muted tag)
  created_at: string;
}

export interface ProposalItem {
  kind: 'proposal';
  id: string;
  session_id: string;
  created_at: string;
  session: SessionMeta;
}

export type FeedItem = ChatItem | ProposalItem;

export interface Feed {
  items: FeedItem[];
  sessions: Record<string, SessionMeta>;
}

export const getFeed = () => apiFetch<Feed>('/feed');
