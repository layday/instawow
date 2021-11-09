<script context="module" lang="ts">
  import type { IconDefinition } from "@fortawesome/fontawesome-common-types";

  export const toCssUrlString = (icon: IconDefinition) => {
    const {
      icon: [width, height, , , svgPathData],
    } = icon;
    const iconSvg = `data:image/svg+xml;utf-8,
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="${width}"
          height="${height}"
          viewBox="0 0 ${width} ${height}">
          <path d="${svgPathData}" fill="#{$fill}" />
        </svg>`;
    return iconSvg;
  };
</script>

<script lang="ts">
  export let icon: IconDefinition;

  const {
    icon: [width, height, , , svgPathData],
    iconName,
    prefix,
  } = icon;
  const d = svgPathData as string;
</script>

<svg
  {width}
  {height}
  viewBox="0 0 {width} {height}"
  class="icon {prefix}-{iconName}"
  {...$$restProps}
>
  <path {d} />
</svg>
