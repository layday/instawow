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
  import { setContext, type Snippet } from "svelte";

  let {
    children,
    onHide,
  }: {
    children: Snippet;
    onHide?: () => void;
  } = $props();

  let eventCoords = $state<EventCoords>();

  let menuWidth = $state(0);
  let menuHeight = $state(0);
  let menuCoords = $state.frozen({ x: 0, y: 0 });

  export const show = (theseEventCoords: EventCoords) => {
    eventCoords = theseEventCoords;
  };

  export const hide = () => {
    eventCoords = undefined;
    onHide?.();
  };

  const hideOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape" && eventCoords) {
      hide();
      event.preventDefault();
    }
  };

  setContext<ContextMenuHandle>("contextMenu", {
    hide,
  });

  $effect(() => {
    if (eventCoords) {
      menuCoords = {
        x:
          eventCoords.x + menuWidth < window.innerWidth
            ? eventCoords.x
            : eventCoords.x - menuWidth,
        y:
          eventCoords.y + menuHeight < window.innerHeight
            ? eventCoords.y
            : eventCoords.y - menuHeight,
      };
    }
  });
</script>

<svelte:window onkeydown={hideOnEsc} onresize={hide} />

{#if eventCoords}
  <div class="context-menu-wrapper" role="presentation" tabindex="-1" onclick={hide}>
    <div
      class="context-menu"
      role="presentation"
      style={`
      --menu-x-offset: ${menuCoords.x}px;
      --menu-y-offset: ${menuCoords.y}px;
    `}
      bind:offsetHeight={menuHeight}
      bind:offsetWidth={menuWidth}
      onclick={(e) => e.stopPropagation()}
    >
      <menu>
        {@render children()}
      </menu>
    </div>
  </div>
{/if}

<style lang="scss">
  @use "../scss/vars";

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
