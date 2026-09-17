# @opsmill/backstage-plugin-infrahub-common

Names shared by the Infrahub frontend and backend plugins.

Small on purpose. It exists because these strings have to match across a
process boundary — the backend writes the annotations, the frontend reads them —
and that is exactly the kind of value that drifts when it is written out twice.

```ts
import {
  INFRAHUB_ANNOTATIONS,
  DEFAULT_BRANCH,
} from '@opsmill/backstage-plugin-infrahub-common';

const id = entity.metadata.annotations?.[INFRAHUB_ANNOTATIONS.id];
```

| Annotation                      | Holds                                  |
| ------------------------------- | -------------------------------------- |
| `infrahub.opsmill.com/instance` | Which Infrahub the entity came from    |
| `infrahub.opsmill.com/id`       | The node UUID, which every panel needs |
| `infrahub.opsmill.com/kind`     | The node's Infrahub kind               |
| `infrahub.opsmill.com/branch`   | The branch the entity was read from    |

The UUID is the stable key; an entity's _name_ is the human-friendly id, which
can change.
