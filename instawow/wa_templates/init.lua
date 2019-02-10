-- file generated automatically
local versionTarget = "2.11.0"
local buildTimeTarget = 20190123023201
if not WeakAuras.versionString then return end
local function needUpdate(actual, target)
   if actual == target then return false end

   local function splitByDot(str)
      str = str or ""
      local t, count = {}, 0
      str:gsub("([^%.%-]+)", function(c)
            count = count + 1
            t[count] = c
      end)
      return t
   end

   actual = splitByDot(actual)
   target = splitByDot(target)

   local c = 1
   while true do
      if not target[c] or not actual[c] then
         return false
      end
      if actual[c] ~= target[c] then
         if tonumber(actual[c]) ~= nil and tonumber(target[c]) ~= nil then
            return tonumber(actual[c]) < tonumber(target[c])
         else
            return actual[c] < target[c]
         end
      end
      c = c + 1
   end
end
if (WeakAuras.buildTime and not (WeakAuras.buildTime == "Dev" or tonumber(WeakAuras.buildTime) >= buildTimeTarget))
or (not WeakAuras.buildTime and needUpdate(WeakAuras.versionString, versionTarget))
then
  WeakAuras.prettyPrint(("WeakAuras Companion requires WeakAuras version >= %s"):format(versionTarget))
  WeakAurasCompanion = nil
  return
end
local L = WeakAuras.L
local count = WeakAuras.CountWagoUpdates()
if count > 0 then
  C_Timer.After(1, function() WeakAuras.prettyPrint((L["There are %i updates to your auras ready to be installed!"]):format(count)) end)
end
