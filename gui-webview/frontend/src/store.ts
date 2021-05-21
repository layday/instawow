import type { Api, Config, Profile } from "./api";
import { writable } from "svelte/store";

// export const notifications = writable<Array<InAppNotification>>([]);

export const profiles = writable<Map<Profile, Config>>(new Map());
export const activeProfile = writable<Profile | undefined>(undefined);
