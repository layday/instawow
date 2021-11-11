import type { Config, Profile } from "./api";
import { readable, writable } from "svelte/store";
import { Api } from "./api";
import { RClient } from "./ipc";

export const profiles = writable<Map<Profile, Config>>(new Map());
export const activeProfile = writable<Profile | undefined>();
export const api = readable(new Api(new RClient()));
