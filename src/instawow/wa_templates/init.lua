-- file generated automatically
local buildTimeTarget = 20190123023201
local waBuildTime = tonumber(WeakAuras and WeakAuras.buildTime or 0)

if waBuildTime and waBuildTime > buildTimeTarget then
  local loadedFrame = CreateFrame("FRAME")
  loadedFrame:RegisterEvent("ADDON_LOADED")
  loadedFrame:SetScript("OnEvent", function(_, _, addonName)
    if addonName == "WeakAurasCompanion" then
      local count = WeakAuras.CountWagoUpdates()
      if count and count > 0 then
        WeakAuras.prettyPrint(WeakAuras.L["There are %i updates to your auras ready to be installed!"]:format(count))
      end
      if WeakAuras.ImportHistory then
        for id, data in pairs(WeakAurasSaved.displays) do
          if data.uid and not WeakAurasSaved.history[data.uid] then
            local slug = WeakAurasCompanion.uids[data.uid]
            if slug then
              local wagoData = WeakAurasCompanion.slugs[slug]
              if wagoData and wagoData.encoded then
                WeakAuras.ImportHistory(wagoData.encoded)
              end
            end
          end
        end
      end
      if WeakAurasCompanion.stash then
        local emptyStash = true
        for _ in pairs(WeakAurasCompanion.stash) do
          emptyStash = false
        end
        if not emptyStash and WeakAuras.StashShow then
          C_Timer.After(5, function() WeakAuras.StashShow() end)
        end
      end
    end
  end)
end

if Plater and Plater.CheckWagoUpdates then
    Plater.CheckWagoUpdates()
end
