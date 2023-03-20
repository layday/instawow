<script lang="ts">
  import { partial } from "lodash";
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import { AddonAction } from "../constants";
  import ContextMenu, { type EventCoords } from "./ContextMenu.svelte";
  import ContextMenuItem from "./ContextMenuItem.svelte";

  interface Details {
    addon: Addon;
    installed: boolean;
    supportsRollback: boolean;
  }

  const dispatch = createEventDispatcher<{
    selectItem: {
      addon: Addon;
      action: AddonAction;
    };
  }>();

  let contextMenu: ContextMenu;

  let details: Details | undefined;

  export const show = (eventCoords: EventCoords, theseDetails: Details) => {
    details = theseDetails;
    contextMenu.show(eventCoords);
  };

  const unsetDetails = () => {
    details = undefined;
  };

  const selectItem = partial(dispatch, "selectItem");
</script>

<ContextMenu bind:this={contextMenu} on:hide={unsetDetails}>
  {#if details}
    {@const { addon } = details}
    {#if details.installed}
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.VisitHomepage })}
        >Visit home page</ContextMenuItem
      >
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.ViewChangelog })}
        >View changelog</ContextMenuItem
      >
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.RevealFolder })}
        >Reveal folder</ContextMenuItem
      >
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Resolve })}
        >Resolve</ContextMenuItem
      >
      <ContextMenuItem divider />
      {#if details.supportsRollback}
        {#if details.addon.logged_versions.length > 1}
          <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Rollback })}
            >Rollback</ContextMenuItem
          >
        {/if}
        {#if details.addon.options.version_eq}
          <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Unpin })}
            >Unpin</ContextMenuItem
          >
        {:else}
          <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Pin })}
            >Pin</ContextMenuItem
          >
        {/if}
      {/if}
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Unreconcile })}
        >Unreconcile</ContextMenuItem
      >
    {:else}
      <ContextMenuItem
        on:click={() => selectItem({ addon, action: AddonAction.InstallAndReplace })}
        >Install and replace</ContextMenuItem
      >
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.ViewChangelog })}
        >View changelog</ContextMenuItem
      >
      <ContextMenuItem divider />
      <ContextMenuItem on:click={() => selectItem({ addon, action: AddonAction.Resolve })}
        >Resolve</ContextMenuItem
      >
    {/if}
  {/if}
</ContextMenu>
