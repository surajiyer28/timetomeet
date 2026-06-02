'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { getFeed, type FeedItem } from '@/lib/api';
import { getUsername, getTimezone } from '@/lib/auth';
import { wsClient } from '@/lib/websocket';
import { speak } from '@/lib/voice';
import StreamItem from './StreamItem';
import Composer from './Composer';

export default function Stream() {
  const myUsername = getUsername() ?? '';
  const myTimezone = getTimezone();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Speak the agent's reply aloud only when the user's last message came in by voice.
  const speakNextRef = useRef(false);

  const reload = useCallback(async () => {
    try {
      const feed = await getFeed();
      setItems(feed.items);
    } catch { /* ignore */ }
    setLoaded(true);
  }, []);

  useEffect(() => {
    reload();

    // Home-channel messages (you + your own agent) arrive individually and append immediately.
    const offChat = wsClient.on('CHAT_MESSAGE', (d) => {
      const m = d.message as { id: string; role: 'user' | 'agent'; content: string; session_id: string | null; created_at: string };
      setItems((prev) => prev.some((i) => i.kind === 'chat' && i.id === m.id)
        ? prev
        : [...prev, { kind: 'chat', participants: [], ...m }]);
      // Speak the agent's reply only if the user's last input was voice.
      if (m.role === 'agent' && speakNextRef.current) {
        speak(m.content);
        speakNextRef.current = false;
      }
      // A meeting-tagged trace: refresh to pick up the meeting tag and any new card.
      if (m.session_id) reload();
    });

    // Negotiation + lifecycle events: re-fetch so attribution and status stay correct.
    const refresh = () => reload();
    const offs = ['MESSAGE', 'PROPOSAL', 'APPROVAL_UPDATE', 'CONFIRMED',
      'RE_NEGOTIATING', 'ESCALATED', 'SESSION_CREATED', 'CANCELLED']
      .map((t) => wsClient.on(t, refresh));

    return () => { offChat(); offs.forEach((o) => o()); };
  }, [reload]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items]);

  const approve = (sessionId: string) => wsClient.send({ type: 'APPROVE', session_id: sessionId });
  const reject = (sessionId: string, reason: string) =>
    wsClient.send({ type: 'REJECT', session_id: sessionId, reason });

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
          {loaded && items.length === 0 && <EmptyState name={myUsername} />}
          {items.map((item) => (
            <StreamItem
              key={`${item.kind}-${item.id}`}
              item={item}
              myUsername={myUsername}
              myTimezone={myTimezone}
              onApprove={approve}
              onReject={reject}
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
      <Composer onSend={(viaVoice) => { speakNextRef.current = viaVoice; }} />
    </div>
  );
}

function EmptyState({ name }: { name: string }) {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <h2 className="text-lg font-semibold text-slate-700">
        Hi{name ? `, ${name}` : ''}.
      </h2>
      <p className="mt-2 text-[15px] leading-relaxed text-slate-500">
        Tell me who you&apos;d like to meet with and I&apos;ll handle the scheduling.
        Try: &ldquo;set up a 30 minute sync with @bob and @carol&rdquo;.
      </p>
    </div>
  );
}
