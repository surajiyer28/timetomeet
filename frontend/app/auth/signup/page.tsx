'use client';
import { useState, FormEvent, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';
import { setAuth } from '@/lib/auth';

export default function SignUp() {
  const router = useRouter();
  const [form, setForm] = useState({ email: '', password: '', name: '', username: '', timezone: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setForm((f) => ({ ...f, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }));
  }, []);

  function update(k: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await apiFetch<{ access_token: string; user_id: string; username: string; timezone: string }>(
        '/auth/signup',
        { method: 'POST', body: JSON.stringify(form) },
      );
      setAuth(data.access_token, data.user_id, data.username, data.timezone);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message ?? 'Sign up failed');
    } finally {
      setLoading(false);
    }
  }

  const field = (label: string, key: keyof typeof form, type = 'text') => (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
      <input
        type={type} value={form[key]} onChange={update(key)} required
        className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />
    </div>
  );

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-slate-900 mb-1">TimeToMeet</h1>
        <p className="text-slate-500 text-sm mb-6">Create your account</p>
        {error && <p className="text-red-600 text-sm mb-4 bg-red-50 rounded-lg p-2">{error}</p>}
        <form onSubmit={handleSubmit} className="space-y-4">
          {field('Full name', 'name')}
          {field('Username', 'username')}
          {field('Email', 'email', 'email')}
          {field('Password', 'password', 'password')}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Timezone</label>
            <input value={form.timezone} readOnly
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 text-slate-500" />
          </div>
          <button
            type="submit" disabled={loading}
            className="w-full bg-indigo-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <p className="text-center text-sm text-slate-500 mt-4">
          Already have an account?{' '}
          <Link href="/auth/signin" className="text-indigo-600 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
