<script lang="ts">
  import { ipcRenderer } from "electron";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";

  export let folders, choices: any[], idx;
</script>

<style lang="scss">
  @import "vars";

  $action-button-bg-color: rgb(24, 136, 255);
  $action-button-text-color: #efefef;

  .addon-stub {
    position: relative;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    &:nth-child(odd) {
      background-color: var(--inverse-color-05);
    }

    ul {
      @include unstyle-list;
    }

    .folders {
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
      margin-top: 0.2em;

      li {
        display: flex;

        label {
          line-height: 1.2em;
          padding: 0 0.5em;
          border-radius: 1em;
        }

        + li {
          margin-left: 0.5em;
        }
      }

      [type="radio"] {
        display: none;

        &:checked + label {
          background-color: $action-button-bg-color;
          font-weight: 500;

          &,
          .name,
          a {
            color: $action-button-text-color;
          }
        }
      }

      .name {
        font-size: 0.8em;
        color: var(--inverse-color-tone-10);
      }

      .defn-and-version {
        padding-left: 0.5em;
        font-family: Menlo, monospace;
        font-size: 0.7em;

        a {
          color: var(--inverse-color-tone-20);
        }
      }
    }
  }
</style>

<li class="addon-stub">
  <div class="folders">
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
  </div>
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
          <span class="name">{choice.name}</span>
          <!-- prettier-ignore -->
          <span class="defn-and-version">
            <a
              href="__openUrl"
              on:click|preventDefault|stopPropagation={() => ipcRenderer.send('open-url', choice.url)}>
              {choice.source}</a><!--
            -->==<!--
            --><span title={choice.date_published}>{choice.version}</span>
          </span>
        </label>
      </li>
    {/each}
    <li>
      <input type="radio" name="addon-selection-{idx}" id="addon-selection-{idx}-skip" value="" />
      <label for="addon-selection-{idx}-skip">
        <span class="name">skip</span>
      </label>
    </li>
  </ul>
</li>
