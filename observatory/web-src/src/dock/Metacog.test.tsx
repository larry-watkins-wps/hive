import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Metacog } from './Metacog';
import { useStore } from '../store';

afterEach(() => {
  cleanup();
  useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 });
});

function pushMetacog(topic: string, source: string, data: unknown, observed_at = Date.now()) {
  useStore.getState().pushEnvelope({
    observed_at,
    topic,
    envelope: { payload: { content_type: 'application/json', data } } as unknown as Record<string, unknown>,
    source_region: source,
    destinations: [],
  });
}

describe('Metacog', () => {
  it('filters to hive/metacognition topics', () => {
    pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'E', detail: 'd' });
    pushMetacog('hive/cognitive/pfc/plan', 'pfc', {});
    const { container } = render(<Metacog />);
    expect(container.querySelectorAll('[data-testid="metacog-row"]').length).toBe(1);
  });

  it('extracts title as kind + ": " + detail for errors', () => {
    pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'LlmError', detail: 'rate_limit' });
    const { getByText } = render(<Metacog />);
    expect(getByText(/LlmError:\s*rate_limit/)).toBeTruthy();
  });
});
