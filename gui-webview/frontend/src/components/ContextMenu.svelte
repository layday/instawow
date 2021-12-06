<script lang="ts">
  import { afterUpdate } from "svelte";

  export let show: boolean, xOffset: number, yOffset: number;

  let offsetHeight: number;
  let offsetWidth: number;

  let topOffset = 0;
  let leftOffset = 0;

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (show = false);

  const adjustPosition = () => {
    topOffset = yOffset + offsetHeight < window.innerHeight ? yOffset : yOffset - offsetHeight;
    leftOffset = xOffset + offsetWidth < window.innerWidth ? xOffset : xOffset - offsetWidth;
  };

  afterUpdate(() => {
    adjustPosition();
  });
</script>

<svelte:window on:keydown={dismissOnEsc} />

<div class="context-menu-wrapper" on:click={() => (show = false)}>
  <div
    bind:offsetHeight
    bind:offsetWidth
    class="context-menu"
    style={`top: ${topOffset}px; left: ${leftOffset}px;`}
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
