<script lang="ts">
  import type { Addon } from "../api";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, addon: Addon, addonListEl: HTMLElement;
</script>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">changelog</div>
    <div class="content">
      {addon.changelog_url}
    </div>
  </dialog>
</Modal>

<style lang="scss">
  @import "scss/modal";
</style>
