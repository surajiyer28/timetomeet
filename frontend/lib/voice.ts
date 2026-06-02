/* Web Speech API wrappers — browser only */

type TranscriptCallback = (text: string) => void;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let recognition: any = null;

export function startListening(onTranscript: TranscriptCallback): () => void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
  if (!SR) return () => {};

  recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  recognition.onresult = (e: any) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const text = Array.from(e.results as any[])
      .map((r: any) => r[0].transcript)
      .join(' ')
      .trim();
    if (text) onTranscript(text);
  };

  recognition.onerror = () => {};
  recognition.start();

  return () => recognition?.stop();
}

const speechQueue: string[] = [];
let speaking = false;

function drainQueue() {
  if (speaking || speechQueue.length === 0) return;
  const text = speechQueue.shift()!;
  speaking = true;
  const utt = new SpeechSynthesisUtterance(text);
  utt.onend = () => {
    speaking = false;
    drainQueue();
  };
  window.speechSynthesis.speak(utt);
}

export function speak(text: string): void {
  speechQueue.push(text);
  drainQueue();
}

export function stopSpeaking(): void {
  speechQueue.length = 0;
  window.speechSynthesis.cancel();
  speaking = false;
}

export const isSpeechSupported = () =>
  typeof window !== 'undefined' &&
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ('SpeechRecognition' in (window as any) || 'webkitSpeechRecognition' in (window as any));
