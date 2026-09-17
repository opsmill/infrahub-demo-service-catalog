import { DEFAULT_BRANCH } from '@opsmill/backstage-plugin-infrahub-common';
import { useEffect, useState } from 'react';

const STORAGE_KEY = 'infrahub.branch';

/**
 * Which Infrahub branch the live panels query. A module-level store rather than
 * a React context: the picker lives in the sidebar and the panels live in the
 * page, and this way neither depends on where a provider got mounted.
 *
 * The catalog itself is always main -- Backstage answers "what exists",
 * Infrahub answers "what is changing" -- so this only steers live queries.
 */
const read = () => {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_BRANCH;
  } catch {
    return DEFAULT_BRANCH;
  }
};

let current = read();
const listeners = new Set<() => void>();

export function setInfrahubBranch(branch: string) {
  current = branch;
  try {
    window.localStorage.setItem(STORAGE_KEY, branch);
  } catch {
    // A browser with storage blocked still gets the choice for this session.
  }
  listeners.forEach(listener => listener());
}

export function useInfrahubBranch() {
  const [branch, setBranch] = useState(current);

  useEffect(() => {
    const listener = () => setBranch(current);
    listeners.add(listener);
    // Another component may have changed it before this one subscribed.
    listener();
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return { branch, setBranch: setInfrahubBranch };
}
