<script lang="ts">
  import { afterUpdate } from "svelte";

  export let show: boolean, xOffset: number, yOffset: number;

  let menuHeight: number;
  let menuWidth: number;
  let menuTopOffset = 0;
  let menuLeftOffset = 0;

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (show = false);

  const adjustPosition = () => {
    menuTopOffset = yOffset + menuHeight < window.innerHeight ? yOffset : yOffset - menuHeight;
    menuLeftOffset = xOffset + menuWidth < window.innerWidth ? xOffset : xOffset - menuWidth;
  };

  afterUpdate(() => {
    adjustPosition();
  });
</script>

<svelte:window on:keydown={dismissOnEsc} />

<div class="context-menu-wrapper" on:click={() => (show = false)}>
  <div
    bind:offsetHeight={menuHeight}
    bind:offsetWidth={menuWidth}
    class="context-menu"
    style={`
      --menu-top-offset: ${menuTopOffset}px;
      --menu-left-offset: ${menuLeftOffset}px;
    `}
    on:click|stopPropagation
  >
    <menu>
      <slot />
    </menu>
  </div>
</div>

<style lang="scss">
  @use "scss/vars";

  .context-menu-wrapper {
    @extend %cover-canvas;
  }

  .context-menu {
    @extend %pop-out;
    position: fixed;
    top: var(--menu-top-offset);
    left: var(--menu-left-offset);
    z-index: 40;
    padding: 0.5em 0;
    background-color: var(--base-color-alpha-65);
    cursor: default;
    white-space: nowrap;

    menu {
      @extend %unstyle-list;
      font-size: 0.8em;
    }
  }
</style>
