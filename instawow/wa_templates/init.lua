{#
   The contents of this file were taken verbatim from
   WeakAuras-Companion <https://github.com/WeakAuras/WeakAuras-Companion>
   which is licensed under the GPLv2.  A copy of the licence is included
   in the enclosing folder.
#}
-- file generated automatically
local buildTimeTarget = 20190123023201
local waBuildTime = tonumber(WeakAuras.buildTime)

if waBuildTime and waBuildTime < buildTimeTarget then
  WeakAurasCompanion = nil
else
  local loadedFrame = CreateFrame("FRAME")
  loadedFrame:RegisterEvent("ADDON_LOADED")
  loadedFrame:SetScript("OnEvent", function(_, _, addonName)
    if addonName == "WeakAurasCompanion" then
      local count = WeakAuras.CountWagoUpdates()
      if count and count > 0 then
        WeakAuras.prettyPrint(WeakAuras.L["There are %i updates to your auras ready to be installed!"]:format(count))
      end
    end
  end)
end
