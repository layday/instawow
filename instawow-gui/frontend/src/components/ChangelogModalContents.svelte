<script lang="ts">
  import { stripHtml } from "string-strip-html";

  const ALLOWED_TAGS = [
    "b",
    "br",
    "code",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "li",
    "p",
    "pre",
    "ul",
  ];

  let {
    changelog,
    renderAsHtml,
  }: {
    changelog: string;
    renderAsHtml: boolean;
  } = $props();
</script>

<div class="title-bar">changelog</div>
<div class="content">
  {#if renderAsHtml}
    <blockquote>
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
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
