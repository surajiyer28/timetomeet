'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { clearAuth } from '@/lib/auth';
import { wsClient } from '@/lib/websocket';
import AvailabilityGrid from './AvailabilityGrid';

interface User { id: string; email: string; name: string; username: string; timezone: string; }

export default function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (open && !user) apiFetch<User>('/users/me').then(setUser).catch(() => {});
  }, [open, user]);

  function signOut() {
    clearAuth();
    wsClient.disconnect();
    router.push('/auth/signin');
  }

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/30 transition-opacity ${open ? 'opacity-100' : 'pointer-events-none opacity-0'}`}
      />
      <aside
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-white shadow-xl transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-800">Settings</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <CloseIcon />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {user && (
            <section className="mb-7">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">Profile</h3>
              <div className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                {[['Name', user.name], ['Handle', `@${user.username}`], ['Email', user.email], ['Timezone', user.timezone]].map(
                  ([label, value]) => (
                    <div key={label} className="flex items-center px-4 py-2.5">
                      <span className="w-24 text-sm text-slate-500">{label}</span>
                      <span className="text-sm font-medium text-slate-800">{value}</span>
                    </div>
                  )
                )}
              </div>
            </section>
          )}

          <section className="mb-7">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">Availability</h3>
            <AvailabilityGrid />
          </section>

          <button
            onClick={signOut}
            className="w-full rounded-lg border border-slate-300 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}
