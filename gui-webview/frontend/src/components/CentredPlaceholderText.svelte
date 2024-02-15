<script lang="ts">
  import type { Snippet } from "svelte";
  import { fade } from "svelte/transition";

  let { children } = $props<{
    children: Snippet;
  }>();
</script>

<div class="placeholder" in:fade>
  <span>{@render children()}</span>
</div>

<style lang="scss">
  .placeholder {
    display: flex;
    flex-grow: 1;
    place-items: center;

    > span {
      flex-grow: 1;
      text-align: center;
    }
  }
</style>
