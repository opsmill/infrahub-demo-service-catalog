export interface Config {
  infrahub?: {
    /**
     * Where the backend calls the Infrahub API. Inside Docker this is a service
     * name, which no browser can resolve -- see externalAddress.
     */
    address: string;

    /**
     * An Infrahub API token.
     * @visibility secret
     */
    token: string;

    /**
     * Where a browser reaches the same Infrahub, used for every link. Defaults
     * to `address`, which is only right when they are the same host.
     */
    externalAddress?: string;

    /**
     * Names this instance in entity annotations, so two Infrahubs in one
     * catalog do not look alike. Defaults to `local`.
     */
    instance?: string;
  };
}
