<script lang="ts">
  import type { Addon } from "../api";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: boolean, changelog: string, asHtml: boolean, addonListEl: HTMLElement;
</script>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">changelog</div>
    <div class="content">
      {#if asHtml}
        {@html changelog}
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

  .modal .content {
    overflow-x: scroll;
  }
</style>
