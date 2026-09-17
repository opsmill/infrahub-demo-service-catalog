export interface Config {
  infrahub?: {
    catalog?: {
      /**
       * How often to read Infrahub, in minutes. Defaults to 1: a request
       * submitted through the scaffolder should appear promptly, and an
       * unchanged read is a no-op mutation.
       */
      refreshMinutes?: number;

      /**
       * The `spec.owner` on every ingested entity. Defaults to
       * `user:default/guest`.
       */
      owner?: string;

      /**
       * A System entity every ingested Component is grouped under. Omit it and
       * no System is emitted -- a plugin should not invent entities nobody
       * asked for.
       */
      system?: string;

      /**
       * Infrahub kinds to ingest, by name. Nothing here lists fields: each
       * kind's own schema decides what the entity says, so adding an attribute
       * in Infrahub needs no change here.
       */
      kinds?: Array<{
        /** The Infrahub kind, e.g. `LocationSite`. */
        kind: string;
        /** The Backstage entity kind. Defaults to `Resource`. */
        entity?: 'Component' | 'Resource' | 'System' | 'API';
        /**
         * The entity's `spec.type`. Defaults to a slug of the Infrahub kind,
         * e.g. `LocationSite` becomes `location-site`.
         */
        type?: string;
        /**
         * Generate a scaffolder template that can create and change objects of
         * this kind. Defaults to true for `Component`, false otherwise --
         * a site is reference data, not something a portal user requests.
         *
         * Set false where you ship a hand-written template for the kind, so
         * users are not offered two forms for the same thing.
         */
        template?: boolean;
        /**
         * Groups a generated create puts the new object into. An Infrahub
         * generator definition targets a *group*, so an object created outside
         * it is never expanded and there is nothing to wait for.
         */
        groups?: string[];
        /**
         * Attributes and relationships the generated form must not offer, on
         * top of `status`. Use it for whatever a generator allocates: those
         * fields are still read and still shown on the entity, but asking a
         * person to type a VLAN the generator picks is just wrong.
         */
        formExclude?: string[];
      }>;

      /**
       * Infrahub generics whose descendants are all ingested. This is what
       * makes the provider schema-driven: a kind added to Infrahub under one of
       * these generics appears on the next read with no config change.
       */
      discover?: Array<{
        /** The Infrahub generic, e.g. `ServiceGeneric`. */
        generic: string;
        /** The Backstage entity kind for every descendant. Defaults to `Component`. */
        entity?: 'Component' | 'Resource' | 'System' | 'API';
        /** Generate create/change templates. Defaults to true. */
        template?: boolean;
        /** Groups every discovered kind's generated create puts objects into. */
        groups?: string[];
        /** Fields no discovered kind's generated form should offer. */
        formExclude?: string[];
      }>;
    };
  };
}
