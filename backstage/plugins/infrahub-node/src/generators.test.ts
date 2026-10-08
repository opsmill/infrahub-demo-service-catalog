import { awaitGenerators } from './generators';
import { infrahubQuery } from './client';

jest.mock('./client', () => ({
  ...jest.requireActual('./client'),
  infrahubQuery: jest.fn(),
}));

const config = {
  instance: 'test',
  address: 'http://infrahub-server:8000',
  externalAddress: 'http://localhost:8000',
  token: 'token',
};

const task = (over: Record<string, unknown> = {}) => ({
  node: {
    id: 'task-1',
    title: 'Run generator dedicated_internet_generator',
    state: 'RUNNING',
    conclusion: null,
    workflow: 'generator-run',
    progress: null,
    error: null,
    logs: { edges: [] },
    ...over,
  },
});

/** A definitions reply, then one tasks reply per poll. */
const ran: string[] = [];

const replies = (waitable: string[], polls: any[][]) => {
  const queue = [...polls];
  ran.length = 0;
  (infrahubQuery as jest.Mock).mockImplementation(async (options: any) => {
    if (options.query.includes('CoreGeneratorDefinitionRun')) {
      ran.push(options.variables.id);
      return { CoreGeneratorDefinitionRun: { ok: true } };
    }
    if (options.query.includes('CoreGeneratorDefinition')) {
      return {
        // The node is in one group, and a definition targeting it expands it.
        CoreGroup: { edges: [{ node: { id: 'group-1' } }] },
        CoreGeneratorDefinition: {
          edges: waitable.map(name => ({
            node: {
              id: `def-${name}`,
              name: { value: name },
              targets: { node: { id: 'group-1' } },
            },
          })),
        },
      };
    }
    const edges = queue.length > 1 ? queue.shift()! : queue[0] ?? [];
    return { InfrahubTask: { count: edges.length, edges } };
  });
};

const run = (over: Record<string, unknown> = {}) => {
  const logged: string[] = [];
  let clock = 0;
  return {
    logged,
    result: awaitGenerators({
      config,
      branch: 'implement_int-042',
      node: 'node-1',
      quietPeriod: 15,
      timeout: 600,
      pollInterval: 5,
      logger: {
        info: (message: string) => logged.push(message),
        warn: (message: string) => logged.push(message),
      } as any,
      // Time only moves when the code sleeps, so the test is instant.
      sleep: async (seconds: number) => {
        clock += seconds * 1000;
      },
      now: () => clock,
      ...over,
    }),
  };
};

describe('awaitGenerators', () => {
  it('does not wait when no definition targets the node', async () => {
    replies([], []);
    const { result, logged } = run();

    await expect(result).resolves.toEqual({ waited: false, tasks: 0 });
    expect(logged.join('\n')).toContain('nothing to expand');
    // Never even asked about tasks.
    expect(
      (infrahubQuery as jest.Mock).mock.calls.filter(([o]) =>
        o.query.includes('InfrahubTask'),
      ),
    ).toHaveLength(0);
  });

  it('runs the definitions that target the node, whatever their flags say', async () => {
    replies(['dedicated_internet_generator'], [[]]);
    const { result, logged } = run();
    await result;

    // Requested explicitly, so it does not depend on execute_after_merge being
    // false in the imported repository config.
    expect(ran).toEqual(['def-dedicated_internet_generator']);
    expect(logged.join('\n')).toContain(
      'Running dedicated_internet_generator on implement_int-042',
    );
  });

  it('waits for a run someone else started when trigger is false', async () => {
    replies(['dedicated_internet_generator'], [[]]);
    await run({ trigger: false }).result;

    expect(ran).toEqual([]);
  });

  it('holds for the quiet period, because one wave can enqueue the next', async () => {
    replies(
      ['dedicated_internet_generator'],
      [
        [task()], // running
        [], // wave one done -- a naive check would stop here
        [task({ id: 'task-2', title: 'Run generator wave two' })], // wave two
        [task({ state: 'COMPLETED', conclusion: 'success' })],
      ],
    );
    const { result, logged } = run();

    await expect(result).resolves.toEqual({ waited: true, tasks: 1 });
    const output = logged.join('\n');
    expect(output).toContain('holding 15s');
    // The second wave was reported, so it was not missed.
    expect(output).toContain('Run generator wave two');
    expect(output).toContain('Generators finished');
  });

  it('streams each task log line once', async () => {
    const withLogs = (messages: string[]) =>
      task({
        logs: {
          edges: messages.map(message => ({
            node: { message, severity: 'INFO' },
          })),
        },
      });
    replies(
      ['dedicated_internet_generator'],
      [
        [withLogs(['Allocating VLAN'])],
        [withLogs(['Allocating VLAN', 'Allocating prefix'])],
        [
          {
            node: {
              ...withLogs(['Allocating VLAN', 'Allocating prefix']).node,
              state: 'COMPLETED',
              conclusion: 'success',
            },
          },
        ],
      ],
    );
    const { result, logged } = run();
    await result;

    expect(logged.filter(l => l.includes('Allocating VLAN'))).toHaveLength(1);
    expect(logged.filter(l => l.includes('Allocating prefix'))).toHaveLength(1);
  });

  it('fails the step when a generator fails, so no proposed change is opened', async () => {
    replies(
      ['dedicated_internet_generator'],
      [
        [
          task({
            state: 'COMPLETED',
            conclusion: 'failure',
            error: { message: 'prefix length cannot be changed' },
          }),
        ],
      ],
    );

    await expect(run().result).rejects.toThrow(
      /failure: prefix length cannot be changed/,
    );
  });

  it('times out with what was still running, leaving the branch alone', async () => {
    replies(['dedicated_internet_generator'], [[task()]]);

    await expect(run({ timeout: 20 }).result).rejects.toThrow(
      /Timed out after 20s.*Run generator dedicated_internet_generator.*left in place/s,
    );
  });
});
