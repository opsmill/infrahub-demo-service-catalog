# @opsmill/backstage-plugin-infrahub-node

Talking to [Infrahub](https://opsmill.com) from a Backstage backend.

Nothing here knows about any particular Infrahub schema, so any backend module
can build on it — an entity provider, a scaffolder action, or something else.

## Use

```ts
import {
  readInfrahubConfig,
  infrahubQuery,
  awaitGenerators,
} from '@opsmill/backstage-plugin-infrahub-node';

const infrahub = readInfrahubConfig(config);

const data = await infrahubQuery({
  config: infrahub,
  query: '{ LocationSite { edges { node { id } } } }',
  branch: 'main',
});
```

Config it reads:

```yaml
infrahub:
  address: http://infrahub-server:8000 # where the backend calls the API
  externalAddress: http://localhost:8000 # where a browser reaches it, for links
  token: ${INFRAHUB_API_TOKEN}
  instance: local # names this instance in annotations
```

`address` and `externalAddress` are deliberately separate: inside Docker the
backend calls a service name no browser can resolve, so a link built from
`address` is a dead link.

`infrahubGet(config, path)` covers the REST API, which is where the schema
lives — `/api/schema`, `/api/schema/{kind}`, `/api/schema/json_schema/{kind}`.

## Waiting for generators

A service object is only half a change: an Infrahub generator expands it
asynchronously, after the mutation returns. `awaitGenerators` finds the
definitions targeting a group the node belongs to, runs them, and waits.

```ts
const { waited, tasks } = await awaitGenerators({
  config: infrahub,
  branch: 'implement_svc-001',
  node: nodeId,
  quietPeriod: 15,
  timeout: 1200,
  pollInterval: 5,
  logger,
});
```

Two things make this harder than one poll, and both are handled:

- **Definitions chain.** One wave finishing can enqueue the next, so "zero
  running tasks" is not "finished". It holds a quiet period — zero running, and
  still zero after `quietPeriod` seconds.
- **Nothing may run on its own.** Whether Infrahub starts a generator on a
  branch depends on repository config applied at import time. So it does not
  wait for something to start: it triggers the runs itself with
  `CoreGeneratorDefinitionRun`, which works whatever those flags say. Pass
  `trigger: false` to wait for a run someone else started.

## Other exports

`mapLimit(items, limit, worker)` runs work in parallel with a ceiling. Serial is
needlessly slow for a per-kind fan-out, and unbounded lets a large estate hammer
Infrahub on a schedule.
