'use client';
import type { FeedItem, SessionMeta } from '@/lib/api';
import AgentAvatar from './AgentAvatar';
import ProposalAction from './ProposalAction';

function clockTime(iso: string, tz: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZone: tz });
}
/** A meeting time, always shown in the viewer's own timezone with the zone label. */
function meetingTime(iso: string, tz: string) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short', timeZone: tz,
  });
}

function meetingTag(participants: string[]): string | undefined {
  if (!participants.length) return undefined;
  return `with ${participants.map((u) => '@' + u).join(', ')}`;
}

interface Props {
  item: FeedItem;
  myUsername: string;
  myTimezone: string;
  onApprove: (sessionId: string) => void;
  onReject: (sessionId: string, reason: string) => void;
}

export default function StreamItem({ item, myUsername, myTimezone, onApprove, onReject }: Props) {
  if (item.kind === 'proposal') {
    return <ProposalCard session={item.session} tz={myTimezone}
      onApprove={() => onApprove(item.session_id)} onReject={(r) => onReject(item.session_id, r)} />;
  }

  // chat — always you, or YOUR OWN agent (other agents are never shown)
  if (item.role === 'user') {
    return <MineBubble text={item.content} time={item.created_at} tz={myTimezone} />;
  }
  return (
    <LeftBubble
      seed={myUsername} label="Your agent" context={meetingTag(item.participants)}
      text={item.content} time={item.created_at} tz={myTimezone}
    />
  );
}

function MineBubble({ text, time, tz }: { text: string; time: string; tz: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[78%]">
        <div className="rounded-2xl rounded-br-md bg-indigo-600 px-3.5 py-2 text-[15px] leading-relaxed text-white">
          {text}
        </div>
        <div className="mt-1 pr-1 text-right text-[11px] text-slate-400">{clockTime(time, tz)}</div>
      </div>
    </div>
  );
}

function LeftBubble({
  seed, label, context, text, time, tz,
}: {
  seed: string; label: string; context?: string; text: string; time: string; tz: string;
}) {
  return (
    <div className="flex gap-2.5">
      <AgentAvatar seed={seed} label={label} self />
      <div className="max-w-[78%]">
        <div className="mb-1 flex items-baseline gap-1.5">
          <span className="text-[13px] font-semibold text-slate-700">{label}</span>
          {context && <span className="text-[11px] text-slate-400">· {context}</span>}
        </div>
        <div className="rounded-2xl rounded-tl-md bg-indigo-50 px-3.5 py-2 text-[15px] leading-relaxed text-slate-800">
          {text}
        </div>
        <div className="mt-1 pl-1 text-[11px] text-slate-400">{clockTime(time, tz)}</div>
      </div>
    </div>
  );
}

/** Standalone card for a meeting that needs a look (proposed / confirmed / escalated). */
function ProposalCard({
  session, tz, onApprove, onReject,
}: {
  session: SessionMeta;
  tz: string;
  onApprove: () => void;
  onReject: (reason: string) => void;
}) {
  const s = session;
  const who = s.participants.length ? s.participants.map((u) => '@' + u).join(', ') : 'your meeting';
  const title = s.purpose || 'Meeting';

  if (s.status === 'CONFIRMED') {
    return (
      <Card tone="emerald">
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        <div className="mt-0.5 text-sm text-emerald-700">
          Confirmed{s.proposed_start ? ` · ${meetingTime(s.proposed_start, tz)}` : ''} · {who}
        </div>
      </Card>
    );
  }
  if (s.status === 'ESCALATED') {
    return (
      <Card tone="rose">
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        <div className="mt-0.5 text-sm text-rose-700">Needs your input · {who}</div>
      </Card>
    );
  }
  // PROPOSED / PENDING_APPROVAL
  return (
    <Card tone="indigo">
      <div className="text-sm font-semibold text-slate-800">{title} · {who}</div>
      <div className="mt-0.5 text-sm text-slate-700">
        Proposed{s.proposed_start ? `: ${meetingTime(s.proposed_start, tz)}` : ''}
      </div>
      {s.my_approval_status === 'PENDING' && <ProposalAction onApprove={onApprove} onReject={onReject} />}
      {s.my_approval_status === 'APPROVED' && <div className="mt-1.5 text-sm text-emerald-700">You approved · waiting on the others</div>}
      {s.my_approval_status === 'REJECTED' && <div className="mt-1.5 text-sm text-rose-700">You declined this time</div>}
    </Card>
  );
}

function Card({ tone, children }: { tone: 'indigo' | 'emerald' | 'rose'; children: React.ReactNode }) {
  const ring = { indigo: 'border-indigo-200 bg-indigo-50/60', emerald: 'border-emerald-200 bg-emerald-50/60', rose: 'border-rose-200 bg-rose-50/60' }[tone];
  return <div className={`mx-auto w-full max-w-md rounded-xl border px-4 py-3 ${ring}`}>{children}</div>;
}
