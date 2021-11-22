import type { Client } from "@open-rpc/client-js";
import lodash from "lodash";

export enum Flavour {
  retail = "retail",
  vanilla_classic = "vanilla_classic",
  burning_crusade_classic = "classic",
}

export enum Strategy {
  default = "default",
  latest = "latest",
  any_flavour = "any_flavour",
  version = "version",
}

export enum ChangelogFormat {
  html = "html",
  markdown = "markdown",
  bbcode = "bbcode",
  raw = "raw",
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
  global_config: {
    config_dir: string;
    auto_update_check: boolean;
    temp_dir: string;
  };
  addon_dir: string;
  game_flavour: Flavour;
  profile: string;
};

export type Sources = {
  [source: string]: {
    source: string;
    name: string;
    supported_strategies: string[];
    supports_rollback: boolean;
    changelog_format: ChangelogFormat;
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
  changelog_url: string;
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
  game_flavours: Flavour[];
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
  toc_source_ids = "toc_source_ids",
  folder_name_subsets = "folder_name_subsets",
  addon_names_with_folder_names = "addon_names_with_folder_names",
}

export type DownloadProgressReport = {
  defn: Defn;
  progress: number;
};

export type Version = {
  installed_version: string;
  new_version: string | null;
};

export type SelectFolderResult = {
  selection: string | null;
};

export type ConfirmDialogueResult = {
  ok: boolean;
};

export type PydanticValidationError = {
  ctx: object;
  loc: string[];
  msg: string;
  type: string;
};

export class Api {
  constructor(private clientWrapper: { client: Promise<Client> }, public profile?: string) {}

  withProfile(profile: string) {
    return new Api(this.clientWrapper, profile);
  }

  private async request(requestObject: Parameters<Client["request"]>[0]) {
    const client = await this.clientWrapper.client;
    return await client.request(requestObject, 0);
  }

  async readProfile(profile: string): Promise<Config> {
    return await this.request({ method: "config/read", params: { profile: profile } });
  }

  async writeProfile(config: Config, infer_game_flavour: boolean): Promise<Config> {
    return await this.request({
      method: "config/write",
      params: { values: config, infer_game_flavour: infer_game_flavour },
    });
  }

  async deleteProfile(profile: string): Promise<void> {
    return await this.request({ method: "config/delete", params: { profile: profile } });
  }

  async listProfiles(): Promise<Profiles> {
    return await this.request({ method: "config/list" });
  }

  async listSources(): Promise<Sources> {
    const result = await this.request({
      method: "sources/list",
      params: { profile: this.profile },
    });
    return lodash.fromPairs(result.map((i: Sources["foo"]) => [i.source, i]));
  }

  async list(): Promise<ListResult> {
    return await this.request({
      method: "list",
      params: { profile: this.profile },
    });
  }

  async search(
    searchTerms: string,
    limit: number,
    sources: string[],
    startDate: string | null
  ): Promise<CatalogueEntry[]> {
    return await this.request({
      method: "search",
      params: {
        profile: this.profile,
        search_terms: searchTerms,
        limit: limit,
        sources: sources,
        start_date: startDate ? new Date(startDate) : null,
      },
    });
  }

  async resolve(defns: Defn[]): Promise<MultiResult> {
    return await this.request({
      method: "resolve",
      params: { profile: this.profile, defns: defns },
    });
  }

  async modifyAddons(
    method: "install" | "update" | "remove" | "pin",
    defns: object[],
    extraParams: { [key: string]: any } = {}
  ): Promise<MultiResult> {
    return await this.request({
      method: method,
      params: { profile: this.profile, defns: defns, ...extraParams },
    });
  }

  async getChangelog(changelogUrl: string): Promise<string> {
    return await this.request({
      method: "get_changelog",
      params: { profile: this.profile, changelog_url: changelogUrl },
    });
  }

  async reconcile(matcher: ReconciliationStage): Promise<ReconcileResult> {
    return await this.request({
      method: "reconcile",
      params: { profile: this.profile, matcher: matcher },
    });
  }

  async getDownloadProgress(): Promise<DownloadProgressReport[]> {
    return await this.request({
      method: "get_download_progress",
      params: { profile: this.profile },
    });
  }

  async getVersion(): Promise<Version> {
    return await this.request({ method: "meta/get_version" });
  }

  async openUrl(url: string): Promise<void> {
    await this.request({ method: "assist/open_url", params: { url } });
  }

  async revealFolder(pathParts: string[]): Promise<void> {
    await this.request({ method: "assist/reveal_folder", params: { path_parts: pathParts } });
  }

  async selectFolder(initialFolder: string | null): Promise<SelectFolderResult> {
    return await this.request({
      method: "assist/select_folder",
      params: { initial_folder: initialFolder },
    });
  }

  async confirm(title: string, message: string): Promise<ConfirmDialogueResult> {
    return await this.request({
      method: "assist/confirm",
      params: { title, message },
    });
  }
}

export const addonToDefn = (addon: Addon): Defn => ({
  source: addon.source,
  alias: addon.id,
  strategy: addon.options.strategy,
  version: addon.version,
});
