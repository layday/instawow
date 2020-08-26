<script lang="ts">
  import type { Addon, AddonMeta, Sources } from "../api";
  import { faHistory, faEllipsisH } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let addon: Addon,
    addonMeta: AddonMeta,
    sources: Sources,
    beingModified: boolean,
    refreshing: boolean;

  const dispatch = createEventDispatcher();

  const requestInstall = () => {
    dispatch("requestInstall", { source: addon.source, name: addon.id });
  };

  const requestReinstall = () => {
    dispatch("requestReinstall", { source: addon.source, name: addon.id });
  };

  const requestUpdate = () => {
    dispatch("requestUpdate", { source: addon.source, name: addon.id });
  };

  const requestRemove = () => {
    dispatch("requestRemove", { source: addon.source, name: addon.id });
  };

  const revealFolder = () =>
    ipcRenderer.send(
      "reveal-addon-folder",
      $profiles[$activeProfile].addon_dir,
      addon.folders[0].name
    );
</script>

<style lang="scss">
  @import "vars";

  .addon {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    &:nth-child(odd) {
      background-color: var(--inverse-color-05);
    }

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

    .defn {
      a {
        color: var(--inverse-color-tone-20);
      }
    }

    .version {
      float: right;
    }

    .defn,
    .version {
      font-family: Menlo, monospace;
      font-size: 0.7em;
      line-height: 2em;
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
    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    padding-left: 0.75em;
    -webkit-user-select: none;

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
        width: 11px;
        height: 11px;
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

<li
  class="addon"
  class:status-damaged={addonMeta.damaged}
  class:status-outdated={addonMeta.new_version && addon.version !== addonMeta.new_version}
  class:status-pinned={addon.options.strategy === 'version'}
  class:status-being-modified={beingModified}>
  <ul class="addon-details">
    <li class="name">{addon.name}</li>
    <!-- prettier-ignore -->
    <li class="version">
      {addon.version}
      (<span title={addon.date_published}><!--
        -->{DateTime.fromISO(addon.date_published).toRelative()}<!--
      --></span>)
      {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
        {`< ${addonMeta.new_version}`}
      {/if}
      {#if addon.options.strategy !== 'default'}@ {addon.options.strategy}{/if}
    </li>
    <li class="defn">
      <a
        href="#__openUrl"
        on:click|preventDefault|stopPropagation={() => ipcRenderer.send('open-url', addon.url)}>
        {addon.source}:{addon.slug}
      </a>
    </li>
    <li class="description">{addon.description || 'No description.'}</li>
  </ul>
  {#if beingModified}
    <div class="modification-status-indicator" in:fade />
  {:else}
    <nav class="addon-actions">
      {#if addonMeta.installed}
        {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
          <button disabled={refreshing} on:click|stopPropagation={requestUpdate}>update</button>
        {/if}
        {#if addonMeta.damaged}
          <button disabled={refreshing} on:click|stopPropagation>reinstall</button>
        {/if}
        {#if addon.logged_versions.length > 1 && sources[addon.source]?.supports_rollback}
          <button
            label="rollback"
            title="rollback"
            disabled={refreshing}
            on:click|stopPropagation
            on:contextmenu|preventDefault>
            <Icon icon={faHistory} />
          </button>
        {/if}
        <button
          label="more"
          title="more"
          disabled={refreshing}
          on:click|stopPropagation={() => revealFolder()}>
          <Icon icon={faEllipsisH} />
        </button>
        <button disabled={refreshing} on:click|stopPropagation={requestRemove}>remove</button>
      {:else}
        <button disabled={refreshing} on:click|stopPropagation={requestInstall}>install</button>
      {/if}
    </nav>
  {/if}
</li>
