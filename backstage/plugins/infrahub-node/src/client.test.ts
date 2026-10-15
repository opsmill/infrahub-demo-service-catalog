import { infrahubQuery, mapLimit, readInfrahubConfig } from './client';

const config = {
  instance: 'test',
  address: 'http://infrahub-server:8000',
  externalAddress: 'http://localhost:8000',
  token: 'token',
};

describe('mapLimit', () => {
  it('returns results in input order, not completion order', async () => {
    const delays = [30, 5, 20, 1];
    const results = await mapLimit(delays, 2, async ms => {
      await new Promise(resolve => setTimeout(resolve, ms));
      return ms;
    });

    expect(results).toEqual(delays);
  });

  it('never exceeds the limit, which is why it exists', async () => {
    let running = 0;
    let peak = 0;

    await mapLimit([...Array(20).keys()], 5, async () => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise(resolve => setTimeout(resolve, 1));
      running -= 1;
    });

    expect(peak).toBeLessThanOrEqual(5);
    expect(peak).toBeGreaterThan(1);
  });

  it('handles an empty list without hanging', async () => {
    await expect(mapLimit([], 5, async () => 1)).resolves.toEqual([]);
  });

  it('rejects if any worker rejects', async () => {
    await expect(
      mapLimit([1, 2], 2, async n => {
        if (n === 2) throw new Error('nope');
        return n;
      }),
    ).rejects.toThrow('nope');
  });
});

describe('readInfrahubConfig', () => {
  const config_ = (values: Record<string, string | undefined>) =>
    ({
      getString: (key: string) => {
        const value = values[key];
        if (value === undefined) throw new Error(`missing ${key}`);
        return value;
      },
      getOptionalString: (key: string) => values[key],
    } as any);

  it('falls back to the API address when no browser address is set', () => {
    const read = readInfrahubConfig(
      config_({
        'infrahub.address': 'http://infrahub-server:8000/',
        'infrahub.token': 't',
      }),
    );

    // Trailing slash stripped, so URLs do not end up with a double slash.
    expect(read.address).toBe('http://infrahub-server:8000');
    expect(read.externalAddress).toBe('http://infrahub-server:8000');
    expect(read.instance).toBe('local');
  });

  it('keeps the browser address separate when given', () => {
    const read = readInfrahubConfig(
      config_({
        'infrahub.address': 'http://infrahub-server:8000',
        'infrahub.externalAddress': 'http://localhost:8000',
        'infrahub.instance': 'demo',
        'infrahub.token': 't',
      }),
    );

    expect(read.externalAddress).toBe('http://localhost:8000');
    expect(read.instance).toBe('demo');
  });
});

describe('infrahubQuery', () => {
  const originalFetch = global.fetch;
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('raises the GraphQL error rather than returning a null body', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ errors: [{ message: 'boom' }] }),
    }) as any;

    await expect(infrahubQuery({ config, query: '{ x }' })).rejects.toThrow(
      'boom',
    );
  });

  it('gives up with a named message when Infrahub never answers', async () => {
    // Abort is what the timeout does; assert the message it turns into.
    global.fetch = jest.fn().mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        });
      });
    }) as any;

    const pending = infrahubQuery({ config, query: '{ x }', branch: 'main' });
    jest.advanceTimersByTime(60_000);

    await expect(pending).rejects.toThrow(
      'Infrahub did not answer POST /graphql/main within 60s',
    );
  });
});
