import { infrahubFetch } from './client';

const respond = (body: unknown, ok = true, status = 200) =>
  jest.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  }) as unknown as typeof fetch;

const call = (fetchFn: typeof fetch) =>
  infrahubFetch<{ LocationRack: { count: number } }>({
    url: 'http://backstage/api/proxy/infrahub/graphql/main',
    query: '{ LocationRack { count } }',
    variables: {},
    branch: 'main',
    fetchFn,
  });

describe('infrahubFetch', () => {
  it('returns the data for a successful query', async () => {
    await expect(
      call(respond({ data: { LocationRack: { count: 4 } } })),
    ).resolves.toEqual({ LocationRack: { count: 4 } });
  });

  it('names the branch in a GraphQL error, because a query can be valid on main and not on a branch', async () => {
    const fetchFn = respond({
      errors: [{ message: "Cannot query field 'ssid'" }],
    });

    await expect(
      infrahubFetch({
        url: 'http://backstage/api/proxy/infrahub/graphql/implement_x',
        query: '{ ServiceWireless { edges { node { ssid { value } } } } }',
        variables: {},
        branch: 'implement_x',
        fetchFn,
      }),
    ).rejects.toThrow("Cannot query field 'ssid' (branch implement_x)");
  });

  it('reports an HTTP failure with its status', async () => {
    await expect(call(respond({}, false, 502))).rejects.toThrow(
      'Infrahub returned 502 on branch main',
    );
  });

  it('does not treat an empty body as success', async () => {
    await expect(call(respond({}))).rejects.toThrow('returned no data');
  });

  it('survives a body that is not JSON', async () => {
    const fetchFn = jest.fn().mockResolvedValue({
      ok: false,
      status: 504,
      json: async () => {
        throw new Error('not json');
      },
    }) as unknown as typeof fetch;

    await expect(call(fetchFn)).rejects.toThrow('Infrahub returned 504');
  });

  it('sends the query and variables as a GraphQL POST', async () => {
    const fetchFn = respond({ data: { LocationRack: { count: 0 } } });
    await infrahubFetch({
      url: 'http://backstage/api/proxy/infrahub/graphql/main',
      query: 'query ($id: ID!) { x }',
      variables: { id: 'abc' },
      branch: 'main',
      fetchFn,
    });

    const [, init] = (fetchFn as jest.Mock).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      query: 'query ($id: ID!) { x }',
      variables: { id: 'abc' },
    });
  });
});
