declare namespace svelteHTML {
  interface HTMLAttributes {
    "on:togaSimulateKeypress"?: EventHandler<CustomEvent<{ action: string }>, Window>;
  }
}
