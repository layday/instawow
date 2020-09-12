import type { Config, Profile } from "./api";
import { writable } from "svelte/store";

export const profiles = writable<Record<Profile, Config>>({});
export const activeProfile = writable<Profile | undefined>(undefined);
