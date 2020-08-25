import type { Client } from "@open-rpc/client-js";
import lodash from "lodash";

export default class Api {
  getClient: () => Promise<Client>;
  profile: string;

  constructor(clientHandle: () => Promise<Client>, profile: string = null) {
    this.getClient = clientHandle;
    this.profile = profile;
  }

  withProfile(profile: string) {
    return new Api(this.getClient, profile);
  }

  async enumerateProfiles() {
    const client = await this.getClient();
    return await client.request({ method: "config.enumerate" }, null);
  }

  async listSources() {
    const client = await this.getClient();
    const result = await client.request(
      { method: "sources.list", params: { profile: this.profile } },
      null
    );
    return lodash.fromPairs(result.map((i) => [i.source, i]));
  }

  async listAddons(checkForUpdates: boolean) {
    const client = await this.getClient();
    return await client.request(
      { method: "list", params: { profile: this.profile, check_for_updates: checkForUpdates } },
      null
    );
  }

  async searchForAddons(searchTerms: string, searchLimit: number) {
    const client = await this.getClient();
    return await client.request(
      {
        method: "search",
        params: { profile: this.profile, search_terms: searchTerms, limit: searchLimit },
      },
      null
    );
  }

  async resolveUris(prospectiveDefns: string[]) {
    const client = await this.getClient();
    return await client.request(
      {
        method: "resolve_uris",
        params: { profile: this.profile, prospective_defns: prospectiveDefns },
      },
      null
    );
  }

  async modifyAddons(
    method: "install" | "update" | "remove",
    defns: object[],
    extraParams: object = {}
  ) {
    const client = await this.getClient();
    return await client.request(
      {
        method: method,
        params: { profile: this.profile, defns: defns, ...extraParams },
      },
      null
    );
  }

  async reconcile(matcher: "toc_ids" | "dir_names" | "toc_names") {
    const client = await this.getClient();
    return await client.request(
      { method: "reconcile", params: { profile: this.profile, matcher: matcher } },
      null
    );
  }

  async getVersion(): Promise<string> {
    const client = await this.getClient();
    return await client.request({ method: "meta.get_version" }, null);
  }
}
