<script context="module" lang="ts">
  export const toCssUrlString = (icon) => {
    const {
      icon: [iconWidth, iconHeight, , , iconPath],
    } = icon;
    const iconSvg = `data:image/svg+xml;utf-8,
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="${iconWidth}"
          height="${iconHeight}"
          viewBox="0 0 ${iconWidth} ${iconHeight}">
          <path d="${iconPath}" fill="#{$fill}" />
        </svg>`;
    return iconSvg;
  };
</script>

<script lang="ts">
  export let icon;

  let {
    icon: [width, height, _ligatures, _unicode, svgPathData],
    iconName,
    prefix,
  } = icon;
</script>

<svg
  {width}
  {height}
  viewBox={`0 0 ${width} ${height}`}
  aria-hidden="true"
  class={`icon ${prefix}-${iconName}`}
  {...$$restProps}>
  <path d={svgPathData} />
</svg>
