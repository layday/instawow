<script lang="ts">
  export let show: boolean, eventX: number, eventY: number;

  let menuX = 0;
  let menuY = 0;
  let menuWidth: number;
  let menuHeight: number;

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (show = false);

  $: menuX = eventX + menuWidth < window.innerWidth ? eventX : eventX - menuWidth;
  $: menuY = eventY + menuHeight < window.innerHeight ? eventY : eventY - menuHeight;
</script>

<svelte:window on:keydown={dismissOnEsc} on:resize={() => (show = false)} />

<div class="context-menu-wrapper" on:click={() => (show = false)}>
  <div
    bind:offsetHeight={menuHeight}
    bind:offsetWidth={menuWidth}
    class="context-menu"
    style={`
      --menu-x-offset: ${menuX}px;
      --menu-y-offset: ${menuY}px;
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
    top: var(--menu-y-offset);
    left: var(--menu-x-offset);
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
