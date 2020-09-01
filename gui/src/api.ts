import type { Client } from "@open-rpc/client-js";
import lodash from "lodash";

export enum Strategies {
  default = "default",
  latest = "latest",
  curse_latest_beta = "curse_latest_beta",
  curse_latest_alpha = "curse_latest_alpha",
  any_flavour = "any_flavour",
  version = "version",
}

export type Defn = {
  source: string;
  name: string;
  strategy?: Strategies;
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
  pinned: boolean;
  new_version: string | null;
};

export type ListResult = [Addon, AddonMeta][];

export type ModifyResult = (["success", [Addon, AddonMeta]] | ["failure" | "error", string])[];

export type AddonMatch = {
  folders: { name: string; version: string }[];
  matches: Addon[];
};

export type ReconcileResult = {
  reconciled: AddonMatch[];
  unreconciled: AddonMatch[];
};

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

  async _request(requestObject: Parameters<Client["request"]>[0]) {
    const client = await this.getClient();
    return await client.request(requestObject, null);
  }

  async readProfile(profile: string): Promise<Config> {
    return await this._request({ method: "config.read", params: { profile: profile } });
  }

  async writeProfile(config: Config): Promise<Config> {
    return await this._request({ method: "config.write", params: { values: config } });
  }

  async enumerateProfiles(): Promise<Profiles> {
    return await this._request({ method: "config.enumerate" });
  }

  async listSources(): Promise<Sources> {
    const result = await this._request({
      method: "sources.list",
      params: { profile: this.profile },
    });
    return lodash.fromPairs(result.map((i) => [i.source, i]));
  }

  async listAddons(checkForUpdates: boolean): Promise<ListResult> {
    return await this._request({
      method: "list",
      params: { profile: this.profile, check_for_updates: checkForUpdates },
    });
  }

  async search(
    searchTerms: string,
    searchLimit: number,
    strategy: Exclude<Strategies, "version">
  ): Promise<ListResult> {
    return await this._request({
      method: "search",
      params: {
        profile: this.profile,
        search_terms: searchTerms,
        limit: searchLimit,
        strategy: strategy,
      },
    });
  }

  async resolve(defns: Defn[]): Promise<ListResult> {
    return await this._request({
      method: "resolve",
      params: { profile: this.profile, defns: defns },
    });
  }

  async resolveUris(
    prospectiveDefns: string[],
    strategy: Exclude<Strategies, "version">
  ): Promise<ListResult> {
    return await this._request({
      method: "resolve_uris",
      params: { profile: this.profile, prospective_defns: prospectiveDefns, strategy: strategy },
    });
  }

  async modifyAddons(
    method: "install" | "update" | "remove" | "pin",
    defns: object[],
    extraParams: object = {}
  ): Promise<ModifyResult> {
    return await this._request({
      method: method,
      params: { profile: this.profile, defns: defns, ...extraParams },
    });
  }

  async reconcile(matcher: "toc_ids" | "dir_names" | "toc_names"): Promise<ReconcileResult> {
    return await this._request({
      method: "reconcile",
      params: { profile: this.profile, matcher: matcher },
    });
  }

  async getVersion(): Promise<Version> {
    return await this._request({ method: "meta.get_version" });
  }
}
