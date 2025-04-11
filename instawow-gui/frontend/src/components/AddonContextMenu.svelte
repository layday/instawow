<script lang="ts">
  import type { Addon } from "../api";
  import { AddonAction } from "../constants";
  import ContextMenu, { type EventCoords } from "./context-menu/ContextMenu.svelte";
  import ContextMenuItem from "./context-menu/ContextMenuItem.svelte";

  interface Details {
    addon: Addon;
    installed: boolean;
    supportsRollback: boolean;
  }

  let {
    onSelectItem,
  }: {
    onSelectItem: (item: { addon: Addon; action: AddonAction }) => void;
  } = $props();

  let contextMenu = $state<ReturnType<typeof ContextMenu>>();

  let details = $state<Details>();

  export const show = (eventCoords: EventCoords, theseDetails: Details) => {
    details = theseDetails;
    contextMenu?.show(eventCoords);
  };

  const unsetDetails = () => {
    details = undefined;
  };

  const makeOnSelectHandler =
    ({ addon }: Details, action: AddonAction) =>
    () =>
      onSelectItem({ addon, action });
</script>

<ContextMenu bind:this={contextMenu} onHide={unsetDetails}>
  {#if details?.installed}
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.VisitHomepage)}
      >Visit home page</ContextMenuItem
    >
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.ViewChangelog)}
      >View changelog</ContextMenuItem
    >
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.RevealFolder)}
      >Reveal folder</ContextMenuItem
    >
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Resolve)}
      >Resolve</ContextMenuItem
    >
    <ContextMenuItem divider />
    {#if details.supportsRollback}
      <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Rollback)}
        >Rollback</ContextMenuItem
      >
      {#if details.addon.options.version_eq}
        <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Unpin)}
          >Unpin</ContextMenuItem
        >
      {:else}
        <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Pin)}
          >Pin</ContextMenuItem
        >
      {/if}
    {/if}
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Unreconcile)}
      >Unreconcile</ContextMenuItem
    >
  {:else if details}
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.InstallAndReplace)}
      >Install and replace</ContextMenuItem
    >
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.ViewChangelog)}
      >View changelog</ContextMenuItem
    >
    <ContextMenuItem divider />
    <ContextMenuItem onSelect={makeOnSelectHandler(details, AddonAction.Resolve)}
      >Resolve</ContextMenuItem
    >
  {/if}
</ContextMenu>
