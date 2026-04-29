import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { ChatInput } from './ChatInput';
import * as api from './api';

describe('ChatInput', () => {
  beforeEach(() => {
    useStore.setState({ pendingChatTurns: {} });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    useStore.setState({ pendingChatTurns: {} });
  });

  it('disables submit when text is empty after trim', async () => {
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, '   ');
    await u.keyboard('{Enter}');
    expect(useStore.getState().pendingChatTurns).toEqual({});
  });

  it('submit on Enter: adds optimistic pending turn and POSTs', async () => {
    const post = vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: '2026-04-29T14:00:00.000Z',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hello');
    await u.keyboard('{Enter}');

    // Optimistic turn appears immediately (keyed by client id, status sending or already-sent
    // if microtasks resolved before this assertion).
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending.length).toBe(1);
    expect(pending[0].text).toBe('hello');
    expect(['sending', 'sent']).toContain(pending[0].status);
    expect(post).toHaveBeenCalledWith('hello', undefined);

    // Wait microtasks: pending turn rekeyed to envelope id.
    await Promise.resolve();
    await Promise.resolve();
    const after = useStore.getState().pendingChatTurns;
    expect(after['env-1']).toBeTruthy();
    expect(after['env-1'].status).toBe('sent');
  });

  it('Shift+Enter inserts a newline and does not submit', async () => {
    const post = vi.spyOn(api, 'postChatText');
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'line one');
    await u.keyboard('{Shift>}{Enter}{/Shift}');
    await u.type(textarea, 'line two');
    expect(textarea.value).toBe('line one\nline two');
    expect(post).not.toHaveBeenCalled();
  });

  it('clears textarea after successful submit', async () => {
    vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: 't',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    expect(textarea.value).toBe('');
  });

  it('flips pending turn to failed on POST error', async () => {
    vi.spyOn(api, 'postChatText').mockRejectedValue(
      new api.ChatPostError('publish_failed', 'broker down'),
    );
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    await Promise.resolve();
    await Promise.resolve();
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending.length).toBe(1);
    expect(pending[0].status).toBe('failed');
    expect(pending[0].errorReason).toMatch(/broker down/);
  });
});
