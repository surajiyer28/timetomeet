'use client';

const PALETTE = [
  'bg-rose-500', 'bg-orange-500', 'bg-amber-500', 'bg-emerald-500',
  'bg-teal-500', 'bg-sky-500', 'bg-violet-500', 'bg-fuchsia-500',
];

function colorFor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** A small round identity chip. `self` renders the user's own agent in the brand accent. */
export default function AgentAvatar({
  seed,
  label,
  self = false,
  size = 28,
}: {
  seed: string;
  label: string;
  self?: boolean;
  size?: number;
}) {
  const initial = (label || '?').replace(/^@/, '').charAt(0).toUpperCase();
  const color = self ? 'bg-indigo-600' : colorFor(seed);
  return (
    <div
      className={`${color} flex shrink-0 items-center justify-center rounded-full font-semibold text-white`}
      style={{ width: size, height: size, fontSize: size * 0.42 }}
      title={label}
    >
      {initial}
    </div>
  );
}
