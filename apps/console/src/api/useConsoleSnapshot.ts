import { useCallback, useEffect, useState } from 'react';
import type { ConsoleSnapshot, DemoDataState } from '../types';
import { loadConsoleSnapshot } from './client';

interface SnapshotState {
  data?: ConsoleSnapshot | null;
  error?: Error;
  loading: boolean;
  reload: () => void;
}

export function useConsoleSnapshot(demoState: DemoDataState): SnapshotState {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Omit<SnapshotState, 'reload'>>({ loading: true });

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setState({ loading: true });

    loadConsoleSnapshot(demoState)
      .then((data) => {
        if (active) setState({ data, loading: false });
      })
      .catch((error: unknown) => {
        if (active) setState({ error: error instanceof Error ? error : new Error('Unknown data error'), loading: false });
      });

    return () => {
      active = false;
    };
  }, [attempt, demoState]);

  return { ...state, reload };
}
