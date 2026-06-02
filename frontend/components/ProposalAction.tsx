'use client';
import { useState } from 'react';

/** Inline approve/reject shown under a proposed time, rendered directly in the stream. */
export default function ProposalAction({
  onApprove,
  onReject,
}: {
  onApprove: () => void;
  onReject: (reason: string) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');

  if (rejecting) {
    return (
      <div className="mt-2 flex items-center gap-2">
        <input
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && reason.trim() && onReject(reason.trim())}
          placeholder="What doesn't work?"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-rose-300"
        />
        <button
          onClick={() => reason.trim() && onReject(reason.trim())}
          className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700"
        >
          Send
        </button>
        <button onClick={() => setRejecting(false)} className="px-2 text-sm text-slate-400 hover:text-slate-600">
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="mt-2 flex gap-2">
      <button
        onClick={onApprove}
        className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
      >
        Approve
      </button>
      <button
        onClick={() => setRejecting(true)}
        className="rounded-lg border border-slate-300 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50"
      >
        Reject
      </button>
    </div>
  );
}
