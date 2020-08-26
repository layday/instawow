import type { Config, Profile } from "./api";
import { writable } from "svelte/store";

export const profiles = writable<Record<Profile, Config>>(undefined);
export const activeProfile = writable<Profile>(undefined);
