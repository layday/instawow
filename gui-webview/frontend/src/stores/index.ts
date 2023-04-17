import { writable } from "svelte/store";
import type { Config, Profile } from "../api";

export const profiles = writable<Record<Profile, Config>>({}),
  activeProfile = writable<Profile | undefined>();

export { alerts } from "./alerts";
export { api } from "./api";
