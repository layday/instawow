import type { Profile, Profiles } from "./api";
import { writable } from "svelte/store";

export const profiles = writable<Profiles>(undefined);
export const activeProfile = writable<Profile>(undefined);
