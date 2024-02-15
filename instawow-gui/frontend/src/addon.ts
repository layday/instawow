import type { Addon } from "./api";

export const isSameAddon = (a: Addon, b: Addon) => a.source === b.source && a.id === b.id;
