<svelte:options immutable={true} />

<script context="module" lang="ts">
  import type { IconDefinition } from "@fortawesome/fontawesome-common-types";
  import type { SVGAttributes } from "svelte/elements";

  export const toCssUrlString = ({ icon: [width, height, , , iconPathData] }: IconDefinition) =>
    `data:image/svg+xml;utf-8,
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="${width}"
          height="${height}"
          viewBox="0 0 ${width} ${height}">
          <path d="${iconPathData}" fill="#{$fill}" />
        </svg>`;
</script>

<script lang="ts">
  let { icon, ...props } = $props<
    {
      icon: IconDefinition;
    } & SVGAttributes<SVGElement>
  >();

  let {
    icon: [width, height, , , iconPathData],
    iconName,
    prefix,
  } = icon;
</script>

<svg {width} {height} viewBox="0 0 {width} {height}" class="icon {prefix}-{iconName}" {...props}>
  <path d={iconPathData as string} />
</svg>
