<script lang="ts">
  import type { Addon, AddonMatch } from "../api";
  import { ipcRenderer } from "electron";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";

  export let folders: AddonMatch[], choices: Addon[], idx: number;
</script>

<style lang="scss">
  @import "vars";

  .addon-stub {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    &:nth-child(odd) {
      background-color: var(--inverse-color-05);
    }

    ul {
      @include unstyle-list;
    }

    .main-col {
      flex-grow: 1;
      overflow-x: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;

      .main-folder {
        font-weight: 500;
      }

      .remaining-folders {
        font-size: 0.8em;
      }
    }

    .choices {
      display: flex;
      flex-wrap: wrap;
      margin-top: 0.2em;
      margin-left: -0.5rem;

      li {
        display: flex;
        align-items: center;
        margin-left: 0.5rem;

        label {
          line-height: 1.2em;
          padding-left: 0.25em;
          border-radius: 1em;
        }
      }

      [type="radio"] {
        -webkit-appearance: none;
        flex-shrink: 0;
        width: 12px;
        height: 12px;
        margin: 0;
        border-radius: 1rem;
        border: 1px solid var(--inverse-color);

        &:checked {
          background-color: var(--inverse-color);
        }
      }

      .defn-and-version {
        font-family: Menlo, monospace;
        font-size: 0.7em;

        a {
          color: var(--inverse-color-tone-20);
        }
      }
    }
  }

  .addon-actions {
    @include unstyle-list;

    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    padding-left: 0.75em;
    -webkit-user-select: none;

    [type="radio"] {
      display: none;

      &:checked + label {
        background-color: $action-button-focus-bg-color;
      }
    }

    label {
      padding: 0 0.75em;
      line-height: 1.8em;
      font-size: 0.8em;
      font-weight: 500;
      border: 0;
      border-radius: 1em;
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      transition: all 0.2s;

      ~ label {
        margin-left: 0.5em;
      }
    }
  }
</style>

<li class="addon-stub">
  <div class="main-col">
    <span class="main-folder">{folders[0].name}</span>
    <span>{folders[0].version}</span>
    {#if folders.length > 1}
      <span class="remaining-folders">
        {folders
          .slice(1)
          .map((f) => f.name)
          .join(', ')}
      </span>
    {/if}
    {#if choices.length}
      <ul class="choices">
        {#each choices as choice, choiceIdx}
          <li>
            <input
              type="radio"
              name="addon-selection-{idx}"
              id="addon-selection-{idx}-{choiceIdx}"
              value=""
              checked={choiceIdx === 0} />
            <label for="addon-selection-{idx}-{choiceIdx}">
              <!-- prettier-ignore -->
              <span class="defn-and-version">
                <a
                  href="__openUrl"
                  on:click|preventDefault|stopPropagation={() => ipcRenderer.send('open-url', choice.url)}>
                  {choice.source}:{choice.slug}</a><!--
                -->==<!--
                --><span title={choice.date_published}>{choice.version}</span>
              </span>
            </label>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
  {#if choices.length}
    <menu class="addon-actions">
      <input type="radio" name="addon-selection-{idx}" id="addon-selection-{idx}-skip" value="" />
      <label for="addon-selection-{idx}-skip">
        <span class="name">skip</span>
      </label>
    </menu>
  {/if}
</li>
