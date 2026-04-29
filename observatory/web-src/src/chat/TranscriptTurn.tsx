/**
 * One row in the chat transcript. Plain text — no card chrome — matching
 * the v3 inspector message style. Spec §6.4.
 */
import type { CSSProperties } from 'react';

type Variant = 'user' | 'hive' | 'audio_placeholder' | 'error';

type Props = {
  variant: Variant;
  speaker: string;
  body: string;
  timestamp: string;       // ISO; rendered HH:MM:SS in mono
  errorReason?: string;
};

const SPEAKER_COLORS: Record<Variant, string> = {
  user: 'rgba(143,197,255,.65)',
  hive: 'rgba(220,180,255,.65)',
  audio_placeholder: 'rgba(220,180,255,.65)',
  error: 'rgba(220,140,140,.7)',
};

function fmtClock(iso: string): string {
  // ISO is "YYYY-MM-DDTHH:MM:SS.sssZ" — substring HH:MM:SS.
  const t = iso.indexOf('T');
  return t >= 0 ? iso.substring(t + 1, t + 9) : iso;
}

const speakerStyle = (variant: Variant): CSSProperties => ({
  fontSize: 9, letterSpacing: '.5px', textTransform: 'uppercase',
  color: SPEAKER_COLORS[variant], marginBottom: 3,
  display: 'flex', justifyContent: 'space-between',
});
const tsStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.6)',
};
const bodyStyle = (variant: Variant): CSSProperties => ({
  fontSize: 11, fontWeight: 200, lineHeight: 1.5,
  color: variant === 'error' ? SPEAKER_COLORS.error : 'rgba(230,232,238,.88)',
});
const rowStyle: CSSProperties = { padding: '10px 16px' };

export function TranscriptTurn({ variant, speaker, body, timestamp, errorReason }: Props) {
  return (
    <div style={rowStyle} data-testid="transcript-turn" data-variant={variant}>
      <div style={speakerStyle(variant)}>
        <span>{speaker}</span>
        <span style={tsStyle}>{fmtClock(timestamp)}</span>
      </div>
      <div style={bodyStyle(variant)}>
        {variant === 'error' && errorReason ? `× failed to send · ${errorReason}` : body}
      </div>
    </div>
  );
}
