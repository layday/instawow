import type { Client } from "@open-rpc/client-js";

enum Flavour {
  retail = "retail",
  classic = "classic",
}

export enum Strategy {
  default = "default",
  latest = "latest",
  curse_latest_beta = "curse_latest_beta",
  curse_latest_alpha = "curse_latest_alpha",
  any_flavour = "any_flavour",
  version = "version",
}

type BaseDefn = {
  source: string;
  alias: string;
};

type SimpleDefn = BaseDefn & { strategy?: Exclude<Strategy, Strategy.version> };

type VersionDefn = BaseDefn & {
  strategy: Strategy.version;
  version: string;
};

export type Defn = SimpleDefn | VersionDefn;

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
  options: { strategy: Strategy };
  deps: { id: string }[];
  logged_versions: { version: string; install_time: string }[];
};

export type AddonWithMeta = Addon & {
  __installed__: boolean;
};

export type ListResult = Addon[];

export type SuccessResult = {
  status: "success";
  addon: Addon;
};

export type ErrorResult = {
  status: "failure" | "error";
  message: string;
};

export type AnyResult = SuccessResult | ErrorResult;

export type MultiResult = AnyResult[];

export type CatalogueEntry = {
  source: string;
  id: string;
  slug: string;
  name: string;
  game_compatibility: Flavour[];
  download_count: number;
  last_updated: string;
  normalised_name: string;
  derived_download_score: number;
};

export type AddonMatch = {
  folders: { name: string; version: string }[];
  matches: Addon[];
};

export type ReconcileResult = {
  reconciled: AddonMatch[];
  unreconciled: AddonMatch[];
};

export enum ReconciliationStage {
  toc_ids = "toc_ids",
  dir_names = "dir_names",
  toc_names = "toc_names",
}

export type Version = {
  installed_version: string;
  new_version: string | null;
};

export type PydanticValidationError = {
  ctx: object;
  loc: string[];
  msg: string;
  type: string;
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
    return await client.request(requestObject, 0);
  }

  async readProfile(profile: string): Promise<Config> {
    return await this._request({ method: "config/read", params: { profile: profile } });
  }

  async writeProfile(config: Config, infer_game_flavour: boolean): Promise<Config> {
    return await this._request({
      method: "config/write",
      params: { values: config, infer_game_flavour: infer_game_flavour },
    });
  }

  async deleteProfile(profile: string): Promise<void> {
    return await this._request({ method: "config/delete", params: { profile: profile } });
  }

  async listProfiles(): Promise<Profiles> {
    return await this._request({ method: "config/list" });
  }

  async listSources(): Promise<Sources> {
    const result = await this._request({
      method: "sources/list",
      params: { profile: this.profile },
    });
    return Object.fromEntries(result.map((i: Sources["foo"]) => [i.source, i]));
  }

  async list(): Promise<ListResult> {
    return await this._request({
      method: "list",
      params: { profile: this.profile },
    });
  }

  async search(
    searchTerms: string,
    searchLimit: number,
    sources: string[] | null
  ): Promise<CatalogueEntry[]> {
    return await this._request({
      method: "search",
      params: {
        profile: this.profile,
        search_terms: searchTerms,
        limit: searchLimit,
        sources: sources,
      },
    });
  }

  async resolve(defns: Defn[]): Promise<MultiResult> {
    return await this._request({
      method: "resolve",
      params: { profile: this.profile, defns: defns },
    });
  }

  async modifyAddons(
    method: "install" | "update" | "remove" | "pin",
    defns: object[],
    extraParams: { [key: string]: any } = {}
  ): Promise<MultiResult> {
    return await this._request({
      method: method,
      params: { profile: this.profile, defns: defns, ...extraParams },
    });
  }

  async reconcile(matcher: ReconciliationStage): Promise<ReconcileResult> {
    return await this._request({
      method: "reconcile",
      params: { profile: this.profile, matcher: matcher },
    });
  }

  async getVersion(): Promise<Version> {
    return await this._request({ method: "meta/get_version" });
  }
}

export const addonToDefn = (addon: Addon): Defn => ({
  source: addon.source,
  alias: addon.id,
  strategy: addon.options.strategy,
  version: addon.version,
});
