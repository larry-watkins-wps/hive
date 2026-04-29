/**
 * Chat input: auto-grow textarea + Enter-to-submit + optimistic lifecycle.
 *
 * Lifecycle (spec §6.5):
 *   1. User hits Enter. Add pending turn with status='sending', keyed by
 *      a temp client id. Clear the textarea.
 *   2. POST /sensory/text/in. On 202 success, rekey the pending turn
 *      from temp id to the server's envelope id and set status='sent'.
 *      The Transcript dedupes by id once the firehose echo arrives.
 *   3. On POST failure, flip the pending turn to status='failed' with the
 *      ChatPostError detail in errorReason. The Transcript renders it as
 *      an error placeholder. The temp id stays — the user can re-type a
 *      fresh message; the failed turn lingers until cleared.
 */
import { useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';

import { useStore, type PendingChatTurn } from '../store';
import { ChatPostError, postChatText } from './api';

let _clientIdCounter = 0;
function nextClientId(): string {
  _clientIdCounter += 1;
  return `chat-client-${Date.now()}-${_clientIdCounter}`;
}

const inputContainerStyle: CSSProperties = {
  borderTop: '1px solid rgba(80,84,96,.25)',
  padding: '10px 14px',
  display: 'flex', flexDirection: 'column', gap: 4,
};
const textareaStyle: CSSProperties = {
  width: '100%', resize: 'none',
  background: 'transparent', border: 'none', outline: 'none',
  color: 'rgba(230,232,238,.9)',
  fontFamily: 'Inter, ui-sans-serif, sans-serif',
  fontWeight: 200, fontSize: 11, lineHeight: 1.5,
};
const hintStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.55)',
  letterSpacing: '.3px',
};

const MAX_ROWS = 6;
const ROW_PX = 16;  // line-height 1.5 × 11px ≈ 16

export function ChatInput() {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const addPending = useStore((s) => s.addPendingChatTurn);
  const resolvePending = useStore((s) => s.resolvePendingChatTurn);
  const failPending = useStore((s) => s.failPendingChatTurn);

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, ROW_PX * (MAX_ROWS + 1));
    el.style.height = `${next}px`;
  }

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed) return;
    const clientId = nextClientId();
    const optimistic: PendingChatTurn = {
      id: clientId,
      text: trimmed,
      speaker: 'Larry',  // server's default; we display the same locally
      timestamp: new Date().toISOString(),
      status: 'sending',
    };
    addPending(optimistic);
    setText('');
    if (ref.current) {
      ref.current.style.height = 'auto';
    }

    try {
      const { id, timestamp } = await postChatText(trimmed, undefined);
      resolvePending(clientId, id, timestamp);
    } catch (e) {
      const reason = e instanceof ChatPostError ? `${e.kind}: ${e.detail}` : String(e);
      failPending(clientId, reason);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <div style={inputContainerStyle}>
      <textarea
        ref={ref}
        rows={2}
        placeholder="say something to hive…"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          autoGrow(e.currentTarget);
        }}
        onKeyDown={onKeyDown}
        style={textareaStyle}
      />
      <div style={hintStyle}>enter to send · esc to dismiss · c to toggle</div>
    </div>
  );
}
