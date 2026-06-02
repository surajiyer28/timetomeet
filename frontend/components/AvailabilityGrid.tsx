'use client';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

interface Entry { day_of_week: number; start_time: string; end_time: string; is_available: boolean; }

const DEFAULT: Entry[] = DAYS.map((_, i) => ({
  day_of_week: i,
  start_time: '09:00:00',
  end_time: '17:00:00',
  is_available: i < 5,
}));

export default function AvailabilityGrid() {
  const [entries, setEntries] = useState<Entry[]>(DEFAULT);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<{ availability: Entry[] }>('/availability')
      .then(({ availability }) => {
        if (availability.length === 0) return;
        setEntries(DEFAULT.map((d) => availability.find((a) => a.day_of_week === d.day_of_week) ?? d));
      })
      .catch(() => {});
  }, []);

  function update(i: number, field: keyof Entry, value: unknown) {
    setEntries((prev) => prev.map((e, idx) => idx === i ? { ...e, [field]: value } : e));
  }

  async function save() {
    setSaving(true);
    try {
      await apiFetch('/availability', { method: 'PUT', body: JSON.stringify({ availability: entries }) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  }

  return (
    <div>
      <div className="space-y-2">
        {entries.map((e, i) => (
          <div key={i} className="flex items-center gap-3 bg-white border border-slate-200 rounded-xl px-4 py-3">
            <input
              type="checkbox" checked={e.is_available}
              onChange={(ev) => update(i, 'is_available', ev.target.checked)}
              className="w-4 h-4 accent-indigo-600"
            />
            <span className="w-24 text-sm font-medium text-slate-700">{DAYS[i]}</span>
            <div className={`flex items-center gap-2 flex-1 ${!e.is_available ? 'opacity-40 pointer-events-none' : ''}`}>
              <input type="time" value={e.start_time.slice(0, 5)}
                onChange={(ev) => update(i, 'start_time', ev.target.value + ':00')}
                className="border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <span className="text-slate-400 text-sm">to</span>
              <input type="time" value={e.end_time.slice(0, 5)}
                onChange={(ev) => update(i, 'end_time', ev.target.value + ':00')}
                className="border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3 mt-4">
        <button onClick={save} disabled={saving}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
          {saving ? 'Saving…' : 'Save availability'}
        </button>
        {saved && <span className="text-green-600 text-sm">Saved!</span>}
      </div>
    </div>
  );
}
