-- Capture short input branches from a supplied BizHawk state.
local state_path = assert(os.getenv("GGA_BRANCH_STATE"), "GGA_BRANCH_STATE required")
local out_dir = assert(os.getenv("GGA_BRANCH_OUT"), "GGA_BRANCH_OUT required")

local function dump(path, address, size, domain)
  local data = memory.read_bytes_as_binary_string(address, size, domain)
  local handle = assert(io.open(path, "wb"))
  handle:write(data)
  handle:close()
end

local function pulse(button)
  joypad.set({[button] = true})
  for _ = 1, 4 do emu.frameadvance() end
  joypad.set({})
  for _ = 1, 12 do emu.frameadvance() end
end

local branches = {
  {"initial", {}},
  {"b", {"B"}},
  {"bb", {"B", "B"}},
  {"bbb", {"B", "B", "B"}},
  {"ba", {"B", "A"}},
  {"b_down", {"B", "Down"}},
  {"b_up", {"B", "Up"}},
  {"b_left", {"B", "Left"}},
  {"b_right", {"B", "Right"}},
  {"bb_down", {"B", "B", "Down"}},
  {"bb_up", {"B", "B", "Up"}},
  {"bb_left", {"B", "B", "Left"}},
  {"bb_right", {"B", "B", "Right"}},
  {"bb_a", {"B", "B", "A"}},
}

client.setwindowsize(2)
for _, branch in ipairs(branches) do
  savestate.load(state_path)
  joypad.set({})
  for _ = 1, 3 do emu.frameadvance() end
  for _, button in ipairs(branch[2]) do pulse(button) end
  local stem = out_dir .. "\\" .. branch[1]
  client.screenshot(stem .. ".png")
  dump(stem .. "_vram.bin", 0, 0x18000, "VRAM")
  dump(stem .. "_palette.bin", 0, 0x400, "PALRAM")
  dump(stem .. "_oam.bin", 0, 0x400, "OAM")
end
client.exit()
