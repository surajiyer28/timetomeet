'use client';
import { useRef, useState } from 'react';
import { wsClient } from '@/lib/websocket';
import { startListening, isSpeechSupported } from '@/lib/voice';

/** Always-present bottom input. Sends USER_MESSAGE to the home agent (no session id).
 * `onSend(viaVoice)` lets the parent decide whether to speak the agent's reply aloud. */
export default function Composer({ onSend }: { onSend?: (viaVoice: boolean) => void }) {
  const [text, setText] = useState('');
  const [listening, setListening] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);

  function send(value: string, viaVoice: boolean) {
    const v = value.trim();
    if (!v) return;
    onSend?.(viaVoice);
    wsClient.send({ type: 'USER_MESSAGE', content: v });
    setText('');
  }

  function toggleMic() {
    if (listening) {
      stopRef.current?.();
      setListening(false);
      return;
    }
    stopRef.current = startListening((transcript) => {
      send(transcript, true);
      setListening(false);
    });
    setListening(true);
  }

  return (
    <div className="border-t border-slate-200 bg-white px-4 py-3">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        {isSpeechSupported() && (
          <button
            onClick={toggleMic}
            title={listening ? 'Stop' : 'Speak'}
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors ${
              listening ? 'bg-rose-100 text-rose-600' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-600'
            }`}
          >
            <MicIcon active={listening} />
          </button>
        )}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text, false); }
          }}
          rows={1}
          placeholder="Message your agent — tell it who you'd like to meet"
          className="max-h-32 flex-1 resize-none rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-[15px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <button
          onClick={() => send(text, false)}
          disabled={!text.trim()}
          title="Send"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition-colors hover:bg-indigo-700 disabled:opacity-40"
        >
          <SendIcon />
        </button>
      </div>
    </div>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" fill={active ? 'currentColor' : 'none'} />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}
