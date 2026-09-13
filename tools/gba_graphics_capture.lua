-- Runtime graphics capture for the G Generation Advance GBA ROM.
--
-- This script intentionally does not inspect or decode the game's text engine.
-- It records the graphics-facing memory state and DMA sources so a later
-- offline pass can map live VRAM tiles back to ROM/RAM data.
--
-- Environment
--   GGA_CAPTURE_OUT          output directory (required)
--   GGA_CAPTURE_TAG          file prefix (default: gba_graphics)
--   GGA_CAPTURE_FRAMES       number of frames (default: 4200)
--   GGA_CAPTURE_INPUT        scripted | none (default: scripted)
--   GGA_CAPTURE_SCREEN_EVERY screenshot period (default: 120)
--   GGA_CAPTURE_SAMPLE_EVERY memory sample period (default: 1)
--   GGA_CAPTURE_RAM_EVERY    IWRAM/EWRAM sample period (default: 120)
--   GGA_CAPTURE_MAX_DMA      maximum bytes copied per DMA source (default: 0x20000)
--   GGA_CAPTURE_BUS_TRACE    aggregate CPU writes to graphics/DMA registers (0/1)

local out_dir = assert(os.getenv("GGA_CAPTURE_OUT"), "GGA_CAPTURE_OUT required")
local tag = os.getenv("GGA_CAPTURE_TAG") or "gba_graphics"
local max_frames = tonumber(os.getenv("GGA_CAPTURE_FRAMES") or "4200")
local input_mode = string.lower(os.getenv("GGA_CAPTURE_INPUT") or "scripted")
local screen_every = tonumber(os.getenv("GGA_CAPTURE_SCREEN_EVERY") or "120")
local sample_every = tonumber(os.getenv("GGA_CAPTURE_SAMPLE_EVERY") or "1")
local ram_every = tonumber(os.getenv("GGA_CAPTURE_RAM_EVERY") or "120")
local max_dma = tonumber(os.getenv("GGA_CAPTURE_MAX_DMA") or "131072")
local bus_trace_value = tostring(os.getenv("GGA_CAPTURE_BUS_TRACE") or "0"):lower()
local bus_trace = bus_trace_value == "1" or bus_trace_value == "true"

local log_path = out_dir .. "\\" .. tag .. ".log"
local log = assert(io.open(log_path, "w"))

local function write(message)
  log:write(message .. "\n")
  log:flush()
  console.log(message)
end

local function lower(value)
  return string.lower(tostring(value or ""))
end

local function safe(value)
  return tostring(value):gsub("[^%w%._%-]", "_")
end

local function hex(value, width)
  width = width or 8
  return string.format("%0" .. tostring(width) .. "X", tonumber(value) or 0)
end

local function read_u8(address, domain)
  local ok, value = pcall(memory.read_u8, address, domain)
  if ok then return tonumber(value) or 0 end
  local ok_old, old_value = pcall(memory.readbyte, address, domain)
  if ok_old then return tonumber(old_value) or 0 end
  return 0
end

local function read_u16(address, domain)
  local ok, value = pcall(memory.read_u16_le, address, domain)
  if ok then return tonumber(value) or 0 end
  return read_u8(address, domain) + read_u8(address + 1, domain) * 0x100
end

local function read_u32(address, domain)
  local ok, value = pcall(memory.read_u32_le, address, domain)
  if ok then return tonumber(value) or 0 end
  return read_u16(address, domain) + read_u16(address + 2, domain) * 0x10000
end

local function read_binary(address, length, domain)
  local ok, value = pcall(memory.read_bytes_as_binary_string, address, length, domain)
  if ok and type(value) == "string" and #value == length then
    return value
  end
  return nil
end

local function hash_region(address, length, domain)
  local ok, value = pcall(memory.hash_region, address, length, domain)
  if ok and value ~= nil then
    return tostring(value)
  end
  return nil
end

local function find_domain(domain_names, wanted)
  local target = lower(wanted)
  for _, name in pairs(domain_names) do
    local n = lower(name)
    if n == target then return tostring(name) end
  end
  return nil
end

local function find_domain_contains(domain_names, needles)
  for _, name in pairs(domain_names) do
    local n = lower(name)
    for _, needle in ipairs(needles) do
      if string.find(n, needle, 1, true) then return tostring(name) end
    end
  end
  return nil
end

local domain_names = memory.getmemorydomainlist()
local domains = {}
for _, name in pairs(domain_names) do
  domains[#domains + 1] = tostring(name)
end
table.sort(domains)

write("ROM|" .. tostring(gameinfo.getromname()))
write("ROM_HASH|" .. tostring(gameinfo.getromhash()))
write("SYSTEM|" .. tostring(emu.getsystemid()))
write("CONFIG|frames=" .. tostring(max_frames) .. "|input=" .. input_mode ..
  "|screen_every=" .. tostring(screen_every) ..
  "|sample_every=" .. tostring(sample_every) ..
  "|ram_every=" .. tostring(ram_every) ..
  "|bus_trace=" .. tostring(bus_trace))
for _, name in ipairs(domains) do
  local ok, size = pcall(memory.getmemorydomainsize, name)
  write("DOMAIN|" .. name .. "|" .. tostring(ok and size or "?"))
end

local system_bus = find_domain(domain_names, "System Bus") or "System Bus"
local rom_domain = find_domain_contains(domain_names, {"rom"})
local vram_domain = find_domain_contains(domain_names, {"vram", "video ram"})
local palette_domain = find_domain_contains(domain_names, {"palette", "pal ram", "pram"})
local oam_domain = find_domain_contains(domain_names, {"oam", "object attribute"})
local iwram_domain = find_domain_contains(domain_names, {"iwram", "internal work ram"})
local ewram_domain = find_domain_contains(domain_names, {"ewram", "external work ram"})

-- A named domain is read at offset zero.  The fallback uses the GBA system bus.
local regions = {
  {label = "vram", bus = 0x06000000, size = 0x18000, domain = vram_domain},
  {label = "palette", bus = 0x05000000, size = 0x00400, domain = palette_domain},
  {label = "oam", bus = 0x07000000, size = 0x00400, domain = oam_domain},
  {label = "iwram", bus = 0x03000000, size = 0x08000, domain = iwram_domain},
  {label = "ewram", bus = 0x02000000, size = 0x40000, domain = ewram_domain},
}
local graphics_regions = {regions[1], regions[2], regions[3]}
local ram_regions = {regions[4], regions[5]}

local function region_address(region)
  if region.domain ~= nil then return 0 end
  return region.bus
end

local function region_domain(region)
  return region.domain or system_bus
end

local function region_hash(region)
  return hash_region(region_address(region), region.size, region_domain(region))
end

local function dump_bytes(filename, data)
  local handle = io.open(filename, "wb")
  if not handle then return false end
  handle:write(data)
  handle:close()
  return true
end

local dump_counts = {}
local function dump_region(region, frame, reason, known_hash)
  local data = read_binary(region_address(region), region.size, region_domain(region))
  if data == nil then
    write("READ_FAIL|" .. region.label .. "|" .. tostring(frame) .. "|" .. region_domain(region))
    return nil
  end
  local filename = string.format("%s\\%s_f%06d_%s_%s.bin", out_dir, tag, frame,
    safe(region.label), safe(reason))
  if not dump_bytes(filename, data) then
    write("WRITE_FAIL|" .. filename)
    return nil
  end
  dump_counts[region.label] = (dump_counts[region.label] or 0) + 1
  write("DUMP|" .. tostring(frame) .. "|" .. region.label .. "|" .. filename ..
    "|" .. tostring(#data) .. "|" .. tostring(known_hash or "") .. "|" .. reason)
  return data
end

local function shot(label, frame)
  local filename = string.format("%s\\%s_f%06d_%s.png", out_dir, tag, frame, safe(label))
  local ok, err = pcall(client.screenshot, filename)
  write("SHOT|" .. tostring(frame) .. "|" .. label .. "|" .. filename ..
    "|ok=" .. tostring(ok) .. "|err=" .. tostring(err))
end

local previous_hash = {}
local previous_ram_hash = {}
local seen_dma = {}
local total_graphics_changes = 0
local total_dma = 0

local bus_write_stats = {
  vram = {count = 0, min = nil, max = nil, samples = {}},
  palette = {count = 0, min = nil, max = nil, samples = {}},
  oam = {count = 0, min = nil, max = nil, samples = {}},
  dma = {count = 0, min = nil, max = nil, samples = {}},
}
local bus_callback_count = 0
local bus_unmatched_count = 0
local bus_unmatched_samples = {}

local function bus_write_region(address)
  if address >= 0x05000000 and address < 0x05000400 then return "palette" end
  if address >= 0x06000000 and address < 0x06018000 then return "vram" end
  if address >= 0x07000000 and address < 0x07000400 then return "oam" end
  if address >= 0x040000B0 and address < 0x040000E0 then return "dma" end
  return nil
end

local function bus_write_callback(address, value, flags)
  bus_callback_count = bus_callback_count + 1
  local region = bus_write_region(tonumber(address) or -1)
  if region == nil then
    bus_unmatched_count = bus_unmatched_count + 1
    if #bus_unmatched_samples < 16 then
      bus_unmatched_samples[#bus_unmatched_samples + 1] =
        hex(address) .. ":" .. hex(value) .. ":" .. hex(flags)
    end
    return
  end
  local stat = bus_write_stats[region]
  local addr = tonumber(address) or 0
  stat.count = stat.count + 1
  stat.min = stat.min == nil and addr or math.min(stat.min, addr)
  stat.max = stat.max == nil and addr or math.max(stat.max, addr)
  if #stat.samples < 8 then
    stat.samples[#stat.samples + 1] = hex(addr) .. ":" .. hex(value) .. ":" .. hex(flags)
  end
end

local function reset_bus_write_stats()
  for _, stat in pairs(bus_write_stats) do
    stat.count = 0
    stat.min = nil
    stat.max = nil
    stat.samples = {}
  end
end

local function flush_bus_write_stats(frame)
  if not bus_trace then return end
  for _, region in ipairs({"vram", "palette", "oam", "dma"}) do
    local stat = bus_write_stats[region]
    if stat.count > 0 then
      write("BUS_WRITE|" .. tostring(frame) .. "|" .. region ..
        "|count=" .. tostring(stat.count) ..
        "|min=" .. hex(stat.min) .. "|max=" .. hex(stat.max) ..
        "|samples=" .. table.concat(stat.samples, ","))
    end
  end
  reset_bus_write_stats()
end

if bus_trace then
  local event_scope = system_bus
  local scope_ok, scope_list = pcall(event.availableScopes)
  if scope_ok and type(scope_list) == "table" then
    for _, candidate in pairs(scope_list) do
      local candidate_name = tostring(candidate)
      write("EVENT_SCOPE|" .. candidate_name)
      if lower(candidate_name) == lower(system_bus) then
        event_scope = candidate_name
      end
    end
  end
  local ok, trace_id = pcall(event.on_bus_write, bus_write_callback, nil,
    "gga_graphics_bus_trace", event_scope)
  if ok then
    write("TRACE|bus_write=enabled|id=" .. tostring(trace_id) .. "|scope=" .. event_scope)
  else
    write("TRACE_FAIL|bus_write|" .. tostring(trace_id))
    bus_trace = false
  end
end

local function gfx_destination(address)
  return (address >= 0x05000000 and address < 0x05000400) or
    (address >= 0x06000000 and address < 0x06018000) or
    (address >= 0x07000000 and address < 0x07000400)
end

local function dma_source_data(source, bytes)
  local length = math.min(bytes, max_dma)
  if length <= 0 then return nil, 0, "" end
  local domain = system_bus
  local address = source
  if rom_domain ~= nil and source >= 0x08000000 and source < 0x0A000000 then
    domain = rom_domain
    address = source - 0x08000000
  end
  local data = read_binary(address, length, domain)
  return data, length, domain
end

local function poll_dma(frame)
  for channel = 0, 3 do
    local base = 0x040000B0 + channel * 12
    local source = read_u32(base, system_bus)
    local destination = read_u32(base + 4, system_bus)
    local count = read_u16(base + 8, system_bus)
    local control = read_u16(base + 10, system_bus)
    local enabled = (control & 0x8000) ~= 0
    if enabled and count > 0 and gfx_destination(destination) then
      local unit = ((control & 0x0400) ~= 0) and 4 or 2
      local bytes = count * unit
      local key = string.format("%08X:%08X:%04X:%04X", source, destination, count, control)
      if seen_dma[channel] ~= key then
        seen_dma[channel] = key
        total_dma = total_dma + 1
        write("DMA|" .. tostring(frame) .. "|" .. tostring(channel) .. "|" ..
          hex(source) .. "|" .. hex(destination) .. "|" .. tostring(count) ..
          "|" .. tostring(unit) .. "|" .. tostring(bytes) .. "|" .. hex(control, 4))
        local data, length, domain = dma_source_data(source, bytes)
        if data ~= nil then
          local filename = string.format("%s\\%s_f%06d_dma%d_src_%s.bin", out_dir, tag,
            frame, channel, hex(source))
          if dump_bytes(filename, data) then
            write("DMA_SRC|" .. tostring(frame) .. "|" .. tostring(channel) .. "|" ..
              hex(source) .. "|" .. hex(destination) .. "|" .. tostring(length) ..
              "|" .. domain .. "|" .. filename)
          end
        end
      end
    end
  end
end

local function sample(frame, force_ram)
  if frame ~= 0 and sample_every > 1 and (frame % sample_every) ~= 0 then
    flush_bus_write_stats(frame)
    return
  end
  local graphics_changed = false
  for _, region in ipairs(graphics_regions) do
    local current = region_hash(region)
    local changed = current == nil or previous_hash[region.label] == nil or
      current ~= previous_hash[region.label]
    if changed then
      graphics_changed = true
      dump_region(region, frame, previous_hash[region.label] == nil and "initial" or "changed", current)
    end
    previous_hash[region.label] = current
  end
  if graphics_changed then total_graphics_changes = total_graphics_changes + 1 end

  -- Work RAM is sampled less often because it is much larger and changes often.
  if force_ram or frame == 0 or (ram_every > 0 and frame % ram_every == 0) then
    for _, region in ipairs(ram_regions) do
      local current = region_hash(region)
      local changed = current == nil or previous_ram_hash[region.label] == nil or
        current ~= previous_ram_hash[region.label]
      if changed then
        dump_region(region, frame, previous_ram_hash[region.label] == nil and "initial" or "changed", current)
      end
      previous_ram_hash[region.label] = current
    end
  end
  poll_dma(frame)
  flush_bus_write_stats(frame)
  if frame == 0 or (screen_every > 0 and frame % screen_every == 0) then
    shot("screen", frame)
  end
end

local function set_input(frame)
  if input_mode ~= "scripted" then
    joypad.set({})
    return
  end
  local phase = frame % 120
  local pulse_index = math.floor(frame / 120)
  local buttons = {}
  if phase >= 1 and phase <= 8 then
    if pulse_index % 5 == 0 then
      buttons["Start"] = true
    else
      buttons["A"] = true
    end
  end
  joypad.set(buttons)
end

client.setwindowsize(3)
sample(0, true)
for frame = 1, max_frames do
  set_input(frame)
  emu.frameadvance()
  sample(frame, false)
end

write("SUMMARY|frames=" .. tostring(max_frames) .. "|graphics_samples=" ..
  tostring(total_graphics_changes) .. "|dma_records=" .. tostring(total_dma) ..
  "|vram_dumps=" .. tostring(dump_counts.vram or 0) ..
  "|palette_dumps=" .. tostring(dump_counts.palette or 0) ..
  "|oam_dumps=" .. tostring(dump_counts.oam or 0) ..
  "|iwram_dumps=" .. tostring(dump_counts.iwram or 0) ..
  "|ewram_dumps=" .. tostring(dump_counts.ewram or 0) ..
  "|bus_callbacks=" .. tostring(bus_callback_count) ..
  "|bus_unmatched=" .. tostring(bus_unmatched_count) ..
  "|bus_unmatched_samples=" .. table.concat(bus_unmatched_samples, ","))
write("DONE|frame=" .. tostring(emu.framecount()))
log:close()
client.exit()
