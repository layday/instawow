<script lang="ts" context="module">
  export interface EventCoords {
    x: number;
    y: number;
  }

  export interface ContextMenuHandle {
    hide(): void;
  }
</script>

<script lang="ts">
  import { setContext } from "svelte";

  let eventCoords: EventCoords | undefined;

  let menuWidth: number;
  let menuHeight: number;

  let menuCoords = {
    x: 0,
    y: 0,
  };

  export const show = (theseEventCoords: EventCoords) => {
    eventCoords = theseEventCoords;
  };

  export const hide = () => {
    eventCoords = undefined;
  };

  const dismissOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape" && eventCoords) {
      hide();
      event.preventDefault();
    }
  };

  setContext("contextMenu", {
    hide,
  });

  $: if (eventCoords) {
    menuCoords.x =
      eventCoords.x + menuWidth < window.innerWidth ? eventCoords.x : eventCoords.x - menuWidth;
    menuCoords.y =
      eventCoords.y + menuHeight < window.innerHeight ? eventCoords.y : eventCoords.y - menuHeight;
  }
</script>

<svelte:window on:keydown={dismissOnEsc} on:resize={hide} />

{#if eventCoords}
  <div class="context-menu-wrapper" tabindex="-1" on:click={hide}>
    <div
      class="context-menu"
      style={`
      --menu-x-offset: ${menuCoords.x}px;
      --menu-y-offset: ${menuCoords.y}px;
    `}
      bind:offsetHeight={menuHeight}
      bind:offsetWidth={menuWidth}
      on:click|stopPropagation
    >
      <menu>
        <slot />
      </menu>
    </div>
  </div>
{/if}

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
