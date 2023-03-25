import { readable, writable } from "svelte/store";
import type { Config, Profile } from "./api";
import { Api } from "./api";
import { RClient } from "./ipc";

export const profiles = writable<Record<Profile, Config>>({});
export const activeProfile = writable<Profile | undefined>();
export const api = readable(new Api(new RClient()));
