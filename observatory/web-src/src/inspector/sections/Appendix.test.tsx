import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/react';
import * as rest from '../../api/rest';
import { Appendix } from './Appendix';
import { useStore } from '../../store';

function seedRegion(
  name: string,
  phase = 'wake',
  last_error_ts: string | null = null,
) {
  useStore.setState({
    regions: {
      [name]: {
        role: 'cognitive',
        llm_model: '',
        stats: {
          phase,
          queue_depth: 0,
          stm_bytes: 0,
          tokens_lifetime: 0,
          handler_count: 0,
          last_error_ts,
          msg_rate_in: 0,
          msg_rate_out: 0,
          llm_in_flight: false,
        },
      },
    },
  });
}

beforeEach(() => {
  useStore.setState({ regions: {} });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Appendix', () => {
  it('renders entries newest-first', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockResolvedValue(
      '## 2026-04-22T10:00:00Z — sleep\n\nfirst entry body\n\n## 2026-04-22T12:00:00Z — sleep\n\nsecond entry body\n',
    );
    seedRegion('pfc');
    const { container, findByText } = render(<Appendix name="pfc" />);
    await findByText(/second entry body/);
    const text = container.textContent ?? '';
    expect(text.indexOf('second entry body')).toBeLessThan(
      text.indexOf('first entry body'),
    );
  });

  it('shows empty state on 404', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(
      new rest.RestError(404, 'missing'),
    );
    seedRegion('fresh');
    const { findByText } = render(<Appendix name="fresh" />);
    expect(
      await findByText(/No appendix yet — region hasn't slept\./i),
    ).toBeTruthy();
  });

  it('surfaces non-404 errors inline', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(
      new rest.RestError(403, 'sandbox'),
    );
    seedRegion('pfc');
    const { findByText } = render(<Appendix name="pfc" />);
    expect(await findByText(/Failed:\s*sandbox/i)).toBeTruthy();
  });

  it('reload triggers refetch', async () => {
    const spy = vi
      .spyOn(rest, 'fetchAppendix')
      .mockResolvedValue('## 2026-04-22T10:00:00Z — sleep\n\nfirst');
    seedRegion('pfc');
    const { findByText, getByText } = render(<Appendix name="pfc" />);
    await findByText(/first/);
    spy.mockResolvedValue('## 2026-04-22T11:00:00Z — sleep\n\nsecond');
    fireEvent.click(getByText(/reload/i));
    await findByText(/second/);
  });
});
