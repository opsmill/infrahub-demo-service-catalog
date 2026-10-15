import {
  coreServices,
  createBackendModule,
} from '@backstage/backend-plugin-api';
import {
  createTemplateAction,
  scaffolderActionsExtensionPoint,
} from '@backstage/plugin-scaffolder-node';
import { refreshInfrahubCatalog } from './provider';
import {
  awaitGenerators,
  infrahubQuery,
  readInfrahubConfig,
} from '@opsmill/backstage-plugin-infrahub-node';

/**
 * Runs a GraphQL query or mutation against Infrahub, on a given branch.
 *
 * ponytail: one generic action instead of one action per service — the
 * service-specific mutations live in the templates.
 */
export const infrahubActionsModule = createBackendModule({
  pluginId: 'scaffolder',
  moduleId: 'infrahub-actions',
  register(env) {
    env.registerInit({
      deps: {
        actions: scaffolderActionsExtensionPoint,
        config: coreServices.rootConfig,
      },
      async init({ actions, config }) {
        const infrahub = readInfrahubConfig(config);

        actions.addActions(
          createTemplateAction({
            id: 'infrahub:generators:await',
            description:
              'Wait for the generators expanding a node to finish on its branch',
            schema: {
              input: {
                branch: z => z.string().describe('The branch they run on'),
                node: z =>
                  z.string().describe('The id of the node they expand'),
                quietPeriod: z =>
                  z
                    .number()
                    .optional()
                    .describe(
                      'Seconds of no activity before calling it finished, ' +
                        'because one wave can enqueue the next (default 15)',
                    ),
                timeout: z =>
                  z
                    .number()
                    .optional()
                    .describe('Seconds before giving up (default 1200)'),
                pollInterval: z =>
                  z
                    .number()
                    .optional()
                    .describe('Seconds between polls (default 5)'),
                trigger: z =>
                  z
                    .boolean()
                    .optional()
                    .describe(
                      'Run the definitions first (default true); false waits ' +
                        'for a run someone else started',
                    ),
              },
              output: {
                waited: z =>
                  z
                    .boolean()
                    .describe('False when no generator runs on a branch here'),
                tasks: z => z.number().describe('How many tasks were seen'),
              },
            },
            async handler(ctx) {
              const result = await awaitGenerators({
                config: infrahub,
                branch: ctx.input.branch,
                node: ctx.input.node,
                quietPeriod: ctx.input.quietPeriod ?? 15,
                timeout: ctx.input.timeout ?? 1200,
                pollInterval: ctx.input.pollInterval ?? 5,
                trigger: ctx.input.trigger,
                logger: ctx.logger,
              });

              ctx.output('waited', result.waited);
              ctx.output('tasks', result.tasks);
            },
          }),
          createTemplateAction({
            id: 'infrahub:catalog:refresh',
            description:
              'Read Infrahub into the catalog now, so a service this run ' +
              'created is there when the run finishes',
            async handler(ctx) {
              await refreshInfrahubCatalog();
              ctx.logger.info('Infrahub catalog refreshed');
            },
          }),
          createTemplateAction({
            id: 'infrahub:graphql:execute',
            description: 'Execute a GraphQL query or mutation against Infrahub',
            schema: {
              input: {
                query: z =>
                  z.string().describe('The GraphQL query or mutation'),
                variables: z =>
                  z.record(z.any()).optional().describe('GraphQL variables'),
                branch: z =>
                  z
                    .string()
                    .optional()
                    .describe('Infrahub branch, defaults to main'),
              },
              output: {
                data: z =>
                  z.record(z.any()).describe('The GraphQL response data'),
                address: z =>
                  z
                    .string()
                    .describe(
                      'The browser-facing Infrahub base URL, for building links',
                    ),
              },
            },
            async handler(ctx) {
              const branch = ctx.input.branch ?? 'main';
              const data = await infrahubQuery({
                config: infrahub,
                query: ctx.input.query,
                variables: ctx.input.variables,
                branch,
              });

              ctx.logger.info(
                `Infrahub mutation succeeded on branch ${branch}`,
              );
              ctx.output('data', data);
              ctx.output('address', infrahub.externalAddress);
            },
          }),
        );
      },
    });
  },
});
