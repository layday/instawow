<script lang="ts">
  import type { Addon, AddonMeta } from "../api";
  import {
    faEllipsisH,
    faExternalLinkSquareAlt,
    faHistory,
    faTasks,
  } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fade, slide } from "svelte/transition";
  import Icon from "./SvgIcon.svelte";

  export let addon: Addon,
    addonMeta: AddonMeta,
    canRollback: boolean,
    beingModified: boolean,
    refreshing: boolean;

  const dispatch = createEventDispatcher();

  const requestInstall = () => dispatch("requestInstall");
  const requestReinstall = () => dispatch("requestReinstall");
  const requestUpdate = () => dispatch("requestUpdate");
  const requestRemove = () => dispatch("requestRemove");
  const requestShowModal = (modal: "install" | "reinstall" | "rollback") =>
    dispatch("requestShowModal", modal);
  const requestShowContexMenu = () => dispatch("requestShowContexMenu");
</script>

<style lang="scss">
  @import "vars";

  .addon {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    &.status-being-modified {
      pointer-events: none;
    }

    &.status-damaged {
      @include striped-background(-45deg, rgba(red, 0.1));
    }

    &.status-outdated {
      @include striped-background(-45deg, rgba(lime, 0.1));
    }

    &.status-pinned {
      @include striped-background(-45deg, rgba(gold, 0.1));
    }
  }

  .addon-details {
    @include unstyle-list;
    flex-grow: 1;
    overflow-x: hidden;

    li {
      display: block;
    }

    .name {
      font-weight: 500;
    }

    .versions {
      float: right;
    }

    .defn,
    .versions {
      margin: 0.25rem 0;
      font-family: $mono-font-stack;
      font-size: 0.7em;
      color: var(--inverse-color-tone-10);
    }

    .description {
      font-size: 0.8em;
      overflow-x: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--inverse-color-tone-10);
    }

    &:hover .description {
      display: block;
    }
  }

  .addon-actions {
    @include unstyle-list;
    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    padding-left: 0.75em;

    button {
      padding: 0 0.75em;
      line-height: 1.8em;
      font-size: 0.8em;
      font-weight: 500;
      border: 0;
      border-radius: 1em;
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: $action-button-focus-bg-color;
      }

      + button {
        margin-left: 0.5em;
      }

      :global(.icon) {
        display: block;
        width: 0.8rem;
        height: 0.8rem;
        fill: $action-button-text-color;
      }
    }
  }

  .modification-status-indicator {
    @include spinner(18px, $action-button-bg-color);
    align-self: center;
    justify-self: right;
    margin-left: 0.75em;
  }
</style>

<div
  class="addon"
  class:status-damaged={addonMeta.damaged}
  class:status-outdated={addonMeta.new_version && addon.version !== addonMeta.new_version}
  class:status-pinned={addon.options.strategy === 'version'}
  class:status-being-modified={beingModified}>
  <ul class="addon-details">
    <li class="name">{addon.name}</li>
    <!-- prettier-ignore -->
    <li class="versions">
      {addon.version}
      (<span title={addon.date_published}><!--
        -->{DateTime.fromISO(addon.date_published).toRelative()}<!--
      --></span>)
      {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
        {"<"} {addonMeta.new_version}
      {/if}
      {#if addon.options.strategy !== 'default'}
        @ {addon.options.strategy}
      {/if}
    </li>
    <li class="defn">{addon.source}:{addon.slug}</li>
    <li class="description">{addon.description || 'No description.'}</li>
  </ul>
  {#if beingModified}
    <div class="modification-status-indicator" in:fade />
  {:else}
    <menu class="addon-actions">
      {#if addonMeta.installed}
        {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
          <button disabled={refreshing} on:click|stopPropagation={requestUpdate}>update</button>
        {/if}
        {#if addonMeta.damaged}
          <button disabled={refreshing} on:click|stopPropagation={() => requestReinstall()}>
            reinstall
          </button>
        {/if}
        {#if addon.logged_versions.length > 1 && canRollback}
          <button
            aria-label="rollback"
            title="rollback"
            disabled={refreshing}
            on:click|stopPropagation={() => requestShowModal('rollback')}>
            <Icon icon={faHistory} />
          </button>
        {/if}
        <button
          aria-label="show options"
          title="show options"
          disabled={refreshing}
          on:click|stopPropagation={() => requestShowContexMenu()}>
          <Icon icon={faEllipsisH} />
        </button>
        <button disabled={refreshing} on:click|stopPropagation={requestRemove}>remove</button>
      {:else}
        <button
          aria-label="install with strategy"
          title="install with strategy"
          disabled={refreshing}
          on:click|stopPropagation={() => requestShowModal('install')}>
          <Icon icon={faTasks} />
        </button>
        <button
          aria-label="open in browser"
          title="open in browser"
          on:click|stopPropagation={() => ipcRenderer.send('open-url', addon.url)}>
          <Icon icon={faExternalLinkSquareAlt} />
        </button>
        <button disabled={refreshing} on:click|stopPropagation={requestInstall}>install</button>
      {/if}
    </menu>
  {/if}
</div>
