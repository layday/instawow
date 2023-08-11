import { writable } from "svelte/store";
import type { Profile } from "../api";

export interface Alert {
  heading: string;
  message: string;
}

export const ANY_PROFILE: unique symbol = Symbol("*");

export const alerts = writable<Record<typeof ANY_PROFILE | Profile, Alert[]>>({
  [ANY_PROFILE]: [],
});
