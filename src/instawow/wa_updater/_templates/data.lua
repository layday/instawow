-- file generated automatically
WeakAurasCompanionData = {
  % for addon_name, addon_payload in addons.items():
  ${addon_name} = {
    slugs = {
    % for slug, aura_metadata in addon_payload:
      [ [=[${slug}]=] ] = {
      % for key, value in aura_metadata.items():
        ${key} = [=[${value}]=],
      % endfor
      },
    % endfor
    },
    stash = {
    },
    stopmotionFiles = {
    },
  },
  % endfor
}
