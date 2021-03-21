<script lang="ts">
  import { stripHtml } from "string-strip-html";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: boolean, changelog: string, asHtml: boolean, addonListEl: HTMLElement;

  const ALLOWED_TAGS = ["code", "p", "ul", "li", "pre", "br", "b", "i"];
</script>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">changelog</div>
    <div class="content">
      {#if asHtml}
        <blockquote>
          {@html stripHtml(changelog, { ignoreTags: ALLOWED_TAGS }).result}
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
    max-height: 75%;
    overflow-y: scroll;

    .content {
      overflow: scroll;
      -webkit-user-select: text;
    }
  }
</style>
