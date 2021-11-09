declare namespace svelte.JSX {
  interface IntrinsicElements {
    sveltewindow: HTMLProps<Window> &
      SvelteWindowProps & {
        ontogaSimulateKeypress?: EventHandler<CustomEvent, Window>;
      };
  }
}
