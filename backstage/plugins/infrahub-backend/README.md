# @opsmill/backstage-plugin-infrahub-backend

Mirror [Infrahub](https://opsmill.com) into the Backstage catalog, and let the
scaffolder write back to it.

Two backend modules, added independently because a consumer may want only one:

```ts
// packages/backend/src/index.ts
import {
  infrahubCatalogModule,
  infrahubActionsModule,
} from '@opsmill/backstage-plugin-infrahub-backend';

backend.add(infrahubCatalogModule);
backend.add(infrahubActionsModule);
```

Both read the config that
[`@opsmill/backstage-plugin-infrahub-node`](../infrahub-node/README.md)
documents.

## The entity provider

`infrahubCatalogModule` reads Infrahub on a schedule and applies a full
mutation, so the catalog is Infrahub's data rather than a copy that can drift.

**There is no per-kind code.** Which Infrahub kinds become which entities comes
from config; what each entity _says_ comes from that kind's own Infrahub
schema. Add an attribute in Infrahub and the entity gains it on the next read.

```yaml
infrahub:
  catalog:
    system: infrahub-services # group Components under this System; omit for none
    owner: user:default/guest # spec.owner on everything ingested
    refreshMinutes: 1

    # Kinds ingested by name. Nothing here lists fields.
    kinds:
      - kind: LocationSite
        entity: Resource # default: Resource
        type: infrahub-site # default: a slug, e.g. location-site
      - kind: DcimGenericDevice
        entity: Resource
        type: infrahub-device
      - kind: ServiceDedicatedInternet
        entity: Component
        # A generator definition targets a *group*, so an object created
        # outside it is never expanded and there is nothing to wait for.
        groups: [automated_dedicated_internet]
        # Fields that generator allocates. Still read, still shown on the
        # entity -- just never asked for on the form.
        formExclude: [vlan, prefix, gateway_ip_address]

    # Generics whose descendants are all ingested. This is the reason to use
    # this plugin: a kind added to Infrahub under one of these turns up on the
    # next read, with its own generated form, with no config change.
    discover:
      - generic: ServiceGeneric
        entity: Component # default: Component
        template: true # default: true -- generate a create/change template
```

Nothing is required. Configure only `discover` and every service kind is
ingested with a working form.

### What each entity gets

| From                                   | Becomes                                                              |
| -------------------------------------- | -------------------------------------------------------------------- |
| The schema's `human_friendly_id`       | The entity name -- what a mutation takes back                        |
| `display_label`                        | The title                                                            |
| Every attribute, with its schema title | The description                                                      |
| Every cardinality-one relationship     | A description line, and a `dependsOn` when the peer is also ingested |
| `status`, where the kind has one       | A tag                                                                |
| An open proposed change on the object  | A `pending-change` tag and a pencil pointing at that change          |

A kind with `template: true` also gets a scaffolder Template that can create
_and_ change objects of that kind, generated from
`/api/schema/json_schema/{kind}` -- a mode switch, per-mode required fields,
and one guarded step per field so a blank never overwrites a value.

Every ingested entity carries the annotations from
[`@opsmill/backstage-plugin-infrahub-common`](../infrahub-common/README.md), so
the node UUID -- the stable key -- travels with the entity while its name stays
the readable hfid.

### Generators need two things said out loud

An Infrahub generator definition targets a **group**, and nothing in the schema
links a kind to the group its generators watch. So `groups` has to be
configured: without it a generated create makes an object no generator will
ever expand, `infrahub:generators:await` correctly finds nothing to wait for,
and the run looks like it skipped the generator.

Whatever that generator allocates then wants `formExclude`. Those fields are
still read and still shown on the entity; they are simply not fields to type,
because the generator is about to fill them in.

### Three more things it is careful about

A field a kind does not have fails the _whole_ GraphQL query, so each kind is
asked only for what its own schema declares.

A dropdown's option labels live in `/api/schema/{kind}`, not in `json_schema`,
so a form built from the latter alone offers `1000` where Infrahub says "One
Gigabit". Both payloads are read and merged into `enumNames`.

A change stacked on a request that has not merged is accepted by Infrahub and
then silently discarded. So while a request is open the pencil goes to that
proposed change, not to the change form; once merged, the form.

## The scaffolder actions

| Action                      | Does                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------- |
| `infrahub:graphql:execute`  | Runs a query or mutation on a branch. Generic, so service-specific mutations live in your templates |
| `infrahub:generators:await` | Waits for the generators expanding a node, streaming their logs into the run page                   |
| `infrahub:catalog:refresh`  | Reads Infrahub now, so a service the run just created is in the catalog before the run finishes     |

`infrahub:catalog:refresh` needs `infrahubCatalogModule` installed; it asks
that provider to read now instead of waiting out its schedule.
