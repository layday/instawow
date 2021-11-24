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

  $middle-border-radius: 0.75em;

  .context-menu-wrapper {
    @extend %cover-canvas;
  }

  .context-menu {
    position: fixed;
    z-index: 40;
    border-radius: $middle-border-radius;
    padding: 0.5em 0;
    background-color: var(--base-color-alpha-65);
    -webkit-backdrop-filter: blur(5px);
    backdrop-filter: blur(5px);
    box-shadow: 0 1rem 3rem var(--inverse-color-alpha-10);
    cursor: default;
    white-space: nowrap;

    menu {
      @extend %unstyle-list;
      font-size: 0.8em;
    }
  }
</style>
