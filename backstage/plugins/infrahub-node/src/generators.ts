import { LoggerService } from '@backstage/backend-plugin-api';
import { InfrahubConfig, infrahubQuery } from './client';

/**
 * The generator definitions that expand this node, found through the groups it
 * belongs to: a definition targets a group, so a node is expanded by whichever
 * definitions target a group it is a member of.
 */
const DEFINITIONS_FOR_NODE = `
  query ($node: [ID]) {
    CoreGroup(members__ids: $node) {
      edges { node { id } }
    }
    CoreGeneratorDefinition {
      edges {
        node {
          id
          name { value }
          targets { node { id } }
        }
      }
    }
  }
`;

const RUN_DEFINITION = `
  mutation ($id: String!, $node: [String!]) {
    CoreGeneratorDefinitionRun(
      data: { id: $id, nodes: $node }
      wait_until_completion: false
    ) {
      ok
    }
  }
`;

const TASKS = `
  query ($node: [String], $branch: String) {
    InfrahubTask(related_node__ids: $node, branch: $branch, log_limit: 20) {
      count
      edges {
        node {
          id
          title
          state
          conclusion
          workflow
          progress
          error { message remediation }
          logs { edges { node { message severity } } }
        }
      }
    }
  }
`;

type TaskNode = {
  id: string;
  title: string;
  state: string | null;
  conclusion: string | null;
  workflow: string | null;
  progress: unknown;
  error: { message?: string | null; remediation?: string | null } | null;
  logs?: { edges: { node: { message: string; severity: string } }[] };
};

const isActive = (task: TaskNode) =>
  !['completed', 'crashed', 'failed', 'cancelled'].includes(
    (task.state ?? '').toLowerCase(),
  );

const isFailure = (task: TaskNode) =>
  ['failure', 'failed', 'crashed'].includes(
    (task.conclusion ?? '').toLowerCase(),
  );

export type AwaitOptions = {
  config: InfrahubConfig;
  branch: string;
  node: string;
  quietPeriod: number;
  timeout: number;
  pollInterval: number;
  logger: Pick<LoggerService, 'info' | 'warn'>;
  /** Set false to wait for a run someone else started. */
  trigger?: boolean;
  /** Injected so tests do not sleep. */
  sleep?: (seconds: number) => Promise<void>;
  now?: () => number;
};

export type AwaitResult = { waited: boolean; tasks: number };

/**
 * Waits until the generators expanding a node have finished on its branch, so a
 * reviewer never opens a half-built proposed change. Reports each task's state
 * and streams its logs as it goes, and fails the step if a generator fails --
 * in which case no proposed change is created and there is nothing to clean up.
 */
export async function awaitGenerators(
  options: AwaitOptions,
): Promise<AwaitResult> {
  const { config, branch, node, quietPeriod, timeout, pollInterval, logger } =
    options;
  const sleep =
    options.sleep ??
    ((seconds: number) =>
      new Promise<void>(resolve => setTimeout(resolve, seconds * 1000)));
  const now = options.now ?? (() => Date.now());

  const schema = await infrahubQuery({
    config,
    query: DEFINITIONS_FOR_NODE,
    variables: { node: [node] },
    branch,
  });

  const groups: string[] = (schema.CoreGroup?.edges ?? []).map(
    (edge: any) => edge.node.id,
  );
  const definitions = (schema.CoreGeneratorDefinition?.edges ?? [])
    .map((edge: any) => edge.node)
    .filter((definition: any) =>
      groups.includes(definition.targets?.node?.id ?? ''),
    );

  if (definitions.length === 0) {
    logger.info(
      'No generator definition targets a group this node belongs to, so there ' +
        'is nothing to expand and the proposed change can open now.',
    );
    return { waited: false, tasks: 0 };
  }

  const waitable: string[] = definitions.map(
    (definition: any) => definition.name.value,
  );

  // Run them explicitly rather than relying on Infrahub to trigger them on the
  // branch: an automatic branch-time run depends on execute_after_merge and
  // execute_in_proposed_change being false in the imported repository config,
  // while a requested run works whatever those are set to.
  if (options.trigger !== false) {
    for (const definition of definitions) {
      logger.info(`Running ${definition.name.value} on ${branch}`);
      await infrahubQuery({
        config,
        query: RUN_DEFINITION,
        variables: { id: definition.id, node: [node] },
        branch,
      });
    }
  }

  logger.info(
    `Waiting for generators on ${branch}: ${waitable.join(', ')} ` +
      `(quiet period ${quietPeriod}s, timeout ${timeout}s)`,
  );

  const deadline = now() + timeout * 1000;
  const reportedState = new Map<string, string>();
  const reportedLogs = new Map<string, number>();
  let quietSince: number | undefined;
  let seen = 0;

  for (;;) {
    const data = await infrahubQuery({
      config,
      query: TASKS,
      variables: { node: [node], branch },
    });
    const tasks: TaskNode[] = (data.InfrahubTask?.edges ?? []).map(
      (edge: any) => edge.node,
    );
    seen = Math.max(seen, tasks.length);

    for (const task of tasks) {
      const state = `${task.state ?? '?'}/${task.conclusion ?? '-'}`;
      if (reportedState.get(task.id) !== state) {
        reportedState.set(task.id, state);
        const progress = task.progress
          ? ` progress ${JSON.stringify(task.progress)}`
          : '';
        logger.info(
          `${task.title} [${task.workflow ?? 'generator'}] ${state}${progress}`,
        );
      }

      // Only the lines we have not already relayed, so the run page reads as a
      // stream rather than repeating itself on every poll.
      const lines = task.logs?.edges ?? [];
      for (const line of lines.slice(reportedLogs.get(task.id) ?? 0)) {
        logger.info(`  ${line.node.severity}: ${line.node.message}`);
      }
      reportedLogs.set(task.id, lines.length);

      if (isFailure(task)) {
        throw new Error(
          `Generator task "${task.title}" ${task.conclusion}: ${
            task.error?.message ?? 'see the logs above'
          }${task.error?.remediation ? ` -- ${task.error.remediation}` : ''}`,
        );
      }
    }

    const active = tasks.filter(isActive);
    if (active.length > 0) {
      // A finishing wave can enqueue the next one, so any activity resets it.
      quietSince = undefined;
    } else if (quietSince === undefined) {
      quietSince = now();
      logger.info(
        `No generator running; holding ${quietPeriod}s in case another wave starts`,
      );
    } else if (now() - quietSince >= quietPeriod * 1000) {
      logger.info(`Generators finished: ${seen} task(s) on ${branch}`);
      return { waited: true, tasks: seen };
    }

    if (now() >= deadline) {
      throw new Error(
        `Timed out after ${timeout}s waiting for generators on ${branch}. ` +
          `Still running: ${
            active.map(task => task.title).join(', ') ||
            'nothing, but the ' + 'quiet period had not elapsed'
          }. The branch is left in place for a human to look at.`,
      );
    }

    await sleep(pollInterval);
  }
}
