import type { Client } from "@open-rpc/client-js";
import type { RequestObject } from "./ipc";

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

export type GlobalConfig = {
  config_dir: string;
  auto_update_check: boolean;
  temp_dir: string;
  access_tokens: {
    github: string | null;
    wago: string | null;
    cfcore: string | null;
  };
};

export type Config = {
  addon_dir: string;
  game_flavour: Flavour;
  profile: string;
};

export type GithubCodesResponse = {
  user_code: string;
  verification_uri: string;
};

export type GithubAuthFlowStatusReport = {
  status: "success" | "failure";
};

export type Source = {
  name: string;
  supported_strategies: string[];
  changelog_format: ChangelogFormat;
};

export type Sources = {
  [source: string]: Source;
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

export enum ReconciliationStage {
  toc_source_ids = "toc_source_ids",
  folder_name_subsets = "folder_name_subsets",
  addon_names_with_folder_names = "addon_names_with_folder_names",
}

export type ReconcileInstalledCandidate = {
  installed_addon: Addon;
  alternative_addons: Addon[];
};

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

  withProfile(profile: string, apiClass: typeof Api = Api) {
    return new apiClass(this.clientWrapper, profile);
  }

  async request(requestObject: RequestObject) {
    const client = await this.clientWrapper.client;
    return await client.request(requestObject, 0);
  }

  async readProfile(profile: string): Promise<Config> {
    return await this.request({ method: "config/read_profile", params: { profile } });
  }

  async writeProfile(
    profile: string,
    addonDir: string,
    gameFlavour: Flavour,
    inferGameFlavour: boolean
  ): Promise<Config> {
    return await this.request({
      method: "config/write_profile",
      params: {
        profile,
        addon_dir: addonDir,
        game_flavour: gameFlavour,
        infer_game_flavour: inferGameFlavour,
      },
    });
  }

  async deleteProfile(profile: string): Promise<void> {
    return await this.request({ method: "config/delete_profile", params: { profile } });
  }

  async listProfiles(): Promise<Profiles> {
    return await this.request({ method: "config/list_profiles" });
  }

  async updateGlobalConfig(cfcoreAccessToken: string | null): Promise<void> {
    return await this.request({
      method: "config/update_global",
      params: { cfcore_access_token: cfcoreAccessToken },
    });
  }

  async readGlobalConfig(): Promise<GlobalConfig> {
    return await this.request({ method: "config/read_global" });
  }

  async initiateGithubAuthFlow(): Promise<GithubCodesResponse> {
    return await this.request({ method: "config/initiate_github_auth_flow" });
  }

  async queryGithubAuthFlowStatus(): Promise<GithubAuthFlowStatusReport> {
    return await this.request({ method: "config/query_github_auth_flow_status" });
  }

  async cancelGithubAuthFlow(): Promise<void> {
    return await this.request({ method: "config/cancel_github_auth_flow" });
  }

  async listSources(): Promise<Sources> {
    return await this.request({
      method: "sources/list",
      params: { profile: this.profile },
    });
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
    startDate: string | null,
    installedOnly: boolean
  ): Promise<CatalogueEntry[]> {
    return await this.request({
      method: "search",
      params: {
        profile: this.profile,
        search_terms: searchTerms,
        limit: limit,
        sources: sources,
        start_date: startDate !== null ? new Date(startDate) : startDate,
        installed_only: installedOnly,
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

  async getChangelog(source: string, changelogUrl: string): Promise<string> {
    return await this.request({
      method: "get_changelog",
      params: { profile: this.profile, source, changelog_url: changelogUrl },
    });
  }

  async reconcile(matcher: ReconciliationStage): Promise<AddonMatch[]> {
    return await this.request({
      method: "reconcile",
      params: { profile: this.profile, matcher: matcher },
    });
  }

  async getReconcileInstalledCandidates(): Promise<ReconcileInstalledCandidate[]> {
    return await this.request({
      method: "get_reconcile_installed_candidates",
      params: { profile: this.profile },
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
