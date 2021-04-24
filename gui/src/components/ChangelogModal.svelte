<script lang="ts">
  import { stripHtml } from "string-strip-html";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: boolean, changelog: string, asHtml: boolean, addonListEl: HTMLElement;

  const ALLOWED_TAGS = ["b", "br", "code", "h1", "h2", "h3", "i", "li", "p", "pre", "ul"];
</script>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">changelog</div>
    <div class="content">
      {#if asHtml}
        <blockquote>
          {@html stripHtml(changelog, {
            ignoreTags: ALLOWED_TAGS,
            dumpLinkHrefsNearby: {
              enabled: true,
              putOnNewLine: false,
              wrapHeads: '<span class="link">&lt;',
              wrapTails: "&gt;</span>",
            },
          }).result}
        </blockquote>
      {:else}
        <pre>
          {changelog}
        </pre>
      {/if}
    </div>
  </dialog>
</Modal>

<style lang="scss">
  @import "scss/modal";

  .modal {
    display: flex;
    flex-direction: column;
    max-height: 75%;

    .content {
      overflow: scroll;
      user-select: text;

      :global(pre) {
        white-space: pre-wrap;
      }

      :global(h1) {
        font-size: 1.4em;
      }

      :global(h2) {
        font-size: 1.2em;
      }

      :global(h3) {
        font-size: 1em;
      }

      :global(.link) {
        word-break: break-all;
      }
    }
  }
</style>
