import { DEFAULT_BRANCH } from '@opsmill/backstage-plugin-infrahub-common';
import { setInfrahubBranch } from './branch';

describe('the branch store', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setInfrahubBranch(DEFAULT_BRANCH);
  });

  it('remembers a chosen branch so a reload keeps it', () => {
    setInfrahubBranch('implement_int-042');

    expect(window.localStorage.getItem('infrahub.branch')).toBe(
      'implement_int-042',
    );
  });

  it('notifies every subscriber, so the sidebar and the panels agree', () => {
    // The store is module level precisely so components in different parts of
    // the tree see the same value.
    const seen: string[] = [];
    // eslint-disable-next-line @typescript-eslint/no-var-requires, global-require
    const { useInfrahubBranch } = require('./branch');
    expect(typeof useInfrahubBranch).toBe('function');

    setInfrahubBranch('one');
    seen.push(window.localStorage.getItem('infrahub.branch')!);
    setInfrahubBranch('two');
    seen.push(window.localStorage.getItem('infrahub.branch')!);

    expect(seen).toEqual(['one', 'two']);
  });

  it('falls back to the default when storage is unavailable', () => {
    const getItem = jest
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    const setItem = jest
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });

    // Must not throw: a browser with site data blocked still has to work.
    expect(() => setInfrahubBranch('implement_x')).not.toThrow();

    getItem.mockRestore();
    setItem.mockRestore();
  });
});
