import type { TogaSimulateKeypressAction } from "./constants";

declare module "svelte/elements" {
  export interface SvelteWindowAttributes {
    ontogaSimulateKeypress?: EventHandler<
      CustomEvent<{
        action: TogaSimulateKeypressAction;
      }>,
      Window
    >;
  }
}
