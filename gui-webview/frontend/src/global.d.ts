import type { TogaSimulateKeypressAction } from "./constants";

declare module "svelte/elements" {
  export interface SvelteWindowAttributes {
    "on:togaSimulateKeypress"?: EventHandler<
      CustomEvent<{
        action: TogaSimulateKeypressAction;
      }>,
      Window
    >;
  }
}
