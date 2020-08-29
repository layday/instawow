import type { Client } from "@open-rpc/client-js";
import lodash from "lodash";

export type Defn = {
  source: string;
  name: string;
  strategy?: string;
  strategy_vals?: string[];
};

export type Profile = string;

export type Profiles = Profile[];

export type Config = {
  addon_dir: string;
  auto_update_check: boolean;
  config_dir: string;
  game_flavour: string;
  profile: string;
  temp_dir: string;
};

export type Sources = {
  [source: string]: {
    source: string;
    name: string;
    supported_strategies: string[];
    supports_rollback: boolean;
  };
};

export type Addon = {
  source: string;
  id: string;
  slug: string;
  name: string;
  description: string;
  url: string;
  download_url: string;
  date_published: string;
  version: string;
  folders: { name: string }[];
  options: { strategy: string };
  deps: { id: string }[];
  logged_versions: { version: string; install_time: string }[];
};

export type AddonMeta = {
  installed: boolean;
  damaged: boolean;
  new_version: string | null;
};

export type ListResult = [Addon, AddonMeta][];

export type ModifyResult = (["success", [Addon, AddonMeta]] | ["failure" | "error", string])[];

export type AddonMatch = {
  name: string;
  version: string;
};

export type ReconcileResult = [[AddonMatch[], Addon[]][], AddonMatch[]];

export type Version = {
  installed_version: string;
  new_version: string | null;
};

export class Api {
  getClient: () => Promise<Client>;
  profile?: string;

  constructor(clientHandle: () => Promise<Client>, profile?: string) {
    this.getClient = clientHandle;
    this.profile = profile;
  }

  withProfile(profile: string) {
    return new Api(this.getClient, profile);
  }

  async readProfile(profile: string): Promise<Config> {
    const client = await this.getClient();
    return await client.request({ method: "config.read", params: { profile: profile } }, null);
  }

  async writeProfile(config: Config): Promise<Config> {
    const client = await this.getClient();
    return await client.request({ method: "config.write", params: { values: config } }, null);
  }

  async enumerateProfiles(): Promise<Profiles> {
    const client = await this.getClient();
    return await client.request({ method: "config.enumerate" }, null);
  }

  async listSources(): Promise<Sources> {
    const client = await this.getClient();
    const result = await client.request(
      { method: "sources.list", params: { profile: this.profile } },
      null
    );
    return lodash.fromPairs(result.map((i) => [i.source, i]));
  }

  async listAddons(checkForUpdates: boolean): Promise<ListResult> {
    const client = await this.getClient();
    return await client.request(
      { method: "list", params: { profile: this.profile, check_for_updates: checkForUpdates } },
      null
    );
  }

  async searchForAddons(searchTerms: string, searchLimit: number): Promise<ListResult> {
    const client = await this.getClient();
    return await client.request(
      {
        method: "search",
        params: { profile: this.profile, search_terms: searchTerms, limit: searchLimit },
      },
      null
    );
  }

  async resolveUris(prospectiveDefns: string[]): Promise<ListResult> {
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
  ): Promise<ModifyResult> {
    const client = await this.getClient();
    return await client.request(
      {
        method: method,
        params: { profile: this.profile, defns: defns, ...extraParams },
      },
      null
    );
  }

  async reconcile(matcher: "toc_ids" | "dir_names" | "toc_names"): Promise<ReconcileResult> {
    const client = await this.getClient();
    return await client.request(
      { method: "reconcile", params: { profile: this.profile, matcher: matcher } },
      null
    );
  }

  async getVersion(): Promise<Version> {
    const client = await this.getClient();
    return await client.request({ method: "meta.get_version" }, null);
  }
}
