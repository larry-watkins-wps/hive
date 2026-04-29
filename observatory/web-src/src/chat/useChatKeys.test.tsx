// observatory/web-src/src/chat/useChatKeys.test.tsx
import { cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../store';
import { useChatKeys } from './useChatKeys';

function Harness() {
  useChatKeys();
  return null;
}

describe('useChatKeys', () => {
  beforeEach(() => {
    useStore.setState({ chatVisible: false });
  });
  afterEach(() => {
    cleanup();
    useStore.setState({ chatVisible: false });
  });

  function fireKey(key: string, target: EventTarget = document.body) {
    const e = new KeyboardEvent('keydown', { key, bubbles: true });
    target.dispatchEvent(e);
  }

  it('c toggles chatVisible', () => {
    render(<Harness />);
    expect(useStore.getState().chatVisible).toBe(false);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(true);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('c is ignored when an input has focus', () => {
    render(<Harness />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    fireKey('c', input);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(input);
  });

  it('c is ignored when a textarea has focus', () => {
    render(<Harness />);
    const ta = document.createElement('textarea');
    document.body.appendChild(ta);
    ta.focus();
    fireKey('c', ta);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(ta);
  });

  it('Esc closes the overlay when chatVisible is true and target is inside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    const overlay = document.createElement('div');
    overlay.setAttribute('data-testid', 'chat-overlay');
    document.body.appendChild(overlay);
    fireKey('Escape', overlay);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(overlay);
  });

  it('Esc is ignored when chatVisible is false', () => {
    render(<Harness />);
    fireKey('Escape');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('Esc is ignored when target is outside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    fireKey('Escape', document.body);
    expect(useStore.getState().chatVisible).toBe(true);
  });
});
