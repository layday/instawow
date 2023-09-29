-- file generated automatically
local loadedFrame = CreateFrame("FRAME")
loadedFrame:RegisterEvent("ADDON_LOADED")
loadedFrame:SetScript("OnEvent", function(_, _, addonName)
  if addonName == "WeakAurasCompanion" then
    if WeakAuras and WeakAuras.AddCompanionData and WeakAurasCompanionData then
      local WeakAurasData = WeakAurasCompanionData.WeakAuras
      if WeakAurasData then
        WeakAuras.AddCompanionData(WeakAurasData)
        WeakAuras.StopMotion.texture_types["WeakAuras Companion"] = WeakAuras.StopMotion.texture_types["WeakAuras Companion"] or {}
        local CompanionTextures = WeakAuras.StopMotion.texture_types["WeakAuras Companion"]
        for fileName, name in pairs(WeakAurasData.stopmotionFiles) do
          CompanionTextures["Interface\\\\AddOns\\\\WeakAurasCompanion\\\\animations\\\\" .. fileName] = name
        end
      end
    end
    if Plater and Plater.AddCompanionData and WeakAurasCompanionData and WeakAurasCompanionData.Plater then
      Plater.AddCompanionData(WeakAurasCompanionData.Plater)
    end
  end
end)
