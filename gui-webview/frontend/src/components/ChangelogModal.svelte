<script lang="ts">
  import { stripHtml } from "string-strip-html";
  import Modal from "./Modal.svelte";

  export let show: boolean, changelog: string, renderAsHtml: boolean;

  const ALLOWED_TAGS = ["b", "br", "code", "h1", "h2", "h3", "i", "li", "p", "pre", "ul"];
</script>

<Modal bind:show>
  <div class="title-bar">changelog</div>
  <div class="content">
    {#if renderAsHtml}
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
</Modal>

<style lang="scss">
  .content {
    overflow: scroll;
    -webkit-user-select: text;
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
</style>
