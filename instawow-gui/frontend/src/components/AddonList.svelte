<script lang="ts">
  import type { Snippet } from "svelte";
  import { slide } from "svelte/transition";

  let {
    children,
  }: {
    children: Snippet;
  } = $props();
</script>

<ul class="addon-list" in:slide={{ duration: 250 }}>
  {@render children()}
</ul>

<style lang="scss">
  @use "scss/vars";

  .addon-list {
    @extend %unstyle-list;
    display: flex;
    flex-direction: column;
    row-gap: 4px;
    margin: 0.8em 0;
    padding: 0 0.8em;

    :global(> li) {
      border-radius: 4px;

      &:nth-child(odd) {
        background-color: var(--base-color);
      }
    }
  }
</style>
