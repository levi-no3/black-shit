-- Blade Ball Auto-Parry for PC Roblox Player
-- Keyless, open-source. Press L to toggle on/off.
-- USE AT YOUR OWN RISK: executors / auto-parry violate Roblox ToS and can get you banned.
-- How to use: 1) Join Blade Ball 2) Execute this file with your executor 3) Press L to toggle

getgenv().BladeAuto = getgenv().BladeAuto or {
    AutoParry = true,
    PingBased = true,
    PingOffset = 1.95,
    TimeThreshold = 0.65, -- seconds until impact to parry (lower = later / riskier)
    EmergencyRadius = 10, -- always parry if this close and targeted
    ClashDistance = 22,   -- spam parry range for clashes
    ClashCooldown = 0.01,
    NormalCooldown = 0.05,
    Visuals = true,
    ToggleKey = Enum.KeyCode.L,
}

local SETTINGS = getgenv().BladeAuto
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local Stats = game:GetService("Stats")
local VIM = game:GetService("VirtualInputManager")

local Player = Players.LocalPlayer
local BallsFolder = workspace:WaitForChild("Balls", 5) or workspace:FindFirstChild("Balls")

local LastClick = 0
local LastBallHit = nil
local IsParrying = false

-- Visual ring
local ring, mesh
pcall(function()
    if SETTINGS.Visuals then
        ring = Instance.new("Part")
        ring.Name = "BladeAutoRing"
        ring.Anchored = true
        ring.CanCollide = false
        ring.CanQuery = false
        ring.Transparency = 0.5
        ring.Color = Color3.fromRGB(0, 255, 255)
        ring.Size = Vector3.new(1, 1, 1)
        ring.Shape = Enum.PartType.Ball
        mesh = Instance.new("SpecialMesh")
        mesh.MeshType = Enum.MeshType.Sphere
        mesh.Scale = Vector3.new(20, 20, 0.5)
        mesh.Parent = ring
        ring.Parent = workspace
    end
end)

UserInputService.InputBegan:Connect(function(input, gpe)
    if gpe then return end
    if input.KeyCode == SETTINGS.ToggleKey then
        SETTINGS.AutoParry = not SETTINGS.AutoParry
        game:GetService("StarterGui"):SetCore("SendNotification", {
            Title = "Blade Auto-Parry",
            Text = SETTINGS.AutoParry and "Enabled" or "Disabled",
            Duration = 2,
        })
    end
end)

local function GetBall()
    if not BallsFolder then return nil end
    local children = BallsFolder:GetChildren()
    for i = 1, #children do
        local v = children[i]
        if v:IsA("BasePart") and v:GetAttribute("realBall") == true then
            return v
        end
    end
    for i = 1, #children do
        local v = children[i]
        if v:IsA("BasePart") and v.AssemblyLinearVelocity.Magnitude > 15 then
            return v
        end
    end
    return children[1]
end

local function IsTargeted(ball)
    if not ball then return false end
    -- Method 1: target attribute (most common)
    local t = ball:GetAttribute("target")
    if t ~= nil then
        if t == Player.Name or t == Player.DisplayName or t == tostring(Player.UserId) then
            return true
        end
    end
    -- Method 2: Highlight on character = you are target
    local char = Player.Character
    if char and char:FindFirstChildOfClass("Highlight") then
        return true
    end
    -- Method 3: red ball = targeting someone (fallback, check distance logic still applies)
    if ball.BrickColor == BrickColor.new("Really red") then
        return true
    end
    return false
end

local function DoParry()
    -- Try 1: server remote (most reliable, no mouse needed)
    pcall(function()
        local rs = game:GetService("ReplicatedStorage")
        local remotes = rs:FindFirstChild("Remotes")
        if remotes then
            local pb = remotes:FindFirstChild("ParryButtonPress")
            if pb then pb:Fire() return end
        end
        local pb2 = rs:FindFirstChild("ParryButtonPress")
        if pb2 then pb2:Fire() return end
    end)
    -- Try 2: firesignal on Block button
    pcall(function()
        local gui = Player:FindFirstChildOfClass("PlayerGui")
        local hotbar = gui and gui:FindFirstChild("Hotbar")
        local block = hotbar and hotbar:FindFirstChild("Block")
        if block and block:IsA("GuiButton") then
            if type(firesignal) == "function" then
                firesignal(block.MouseButton1Up)
                return
            elseif type(firesignal) == "function" then
                -- handled above
            end
        end
    end)
    -- Try 3: virtual click (works even if GUI changed)
    pcall(function()
        VIM:SendMouseButtonEvent(0, 0, 0, true, game, 0)
        VIM:SendMouseButtonEvent(0, 0, 0, false, game, 0)
    end)
end

local function SendClick(isClash, ball)
    if not SETTINGS.AutoParry or IsParrying then return end
    local now = tick()
    local cd = isClash and SETTINGS.ClashCooldown or SETTINGS.NormalCooldown
    if not isClash and LastBallHit == ball and (now - LastClick) < 0.5 then return end
    if (now - LastClick) < cd then return end
    IsParrying = true
    LastClick = now
    LastBallHit = ball
    DoParry()
    task.delay(cd, function() IsParrying = false end)
end

local function GetPingSeconds()
    local ok, ping = pcall(function()
        return Stats.Network.ServerStatsItem["Data Ping"]:GetValue() / 1000
    end)
    if ok and type(ping) == "number" then return ping end
    return 0.04
end

RunService.PostSimulation:Connect(function()
    if not SETTINGS.AutoParry then
        if ring then ring.Transparency = 1 end
        return
    end
    local char = Player.Character
    local root = char and char:FindFirstChild("HumanoidRootPart")
    if not root then
        if ring then ring.Transparency = 1 end
        return
    end
    local ball = GetBall()
    if not ball or not ball.Parent then
        if ring then ring.Transparency = 1 end
        return
    end

    local ballPos, playerPos = ball.Position, root.Position
    local vel = ball.AssemblyLinearVelocity
    local speed = vel.Magnitude
    local dist = (playerPos - ballPos).Magnitude

    -- Visuals
    if ring and mesh then
        ring.CFrame = root.CFrame * CFrame.new(0, -2.6, 0) * CFrame.Angles(math.rad(90), 0, 0)
        local s = math.clamp(dist * 0.8, 5, 65)
        mesh.Scale = mesh.Scale:Lerp(Vector3.new(s, s, 0.5), 0.5)
        ring.Transparency = 0.35
    end

    local targeted = IsTargeted(ball)
    local dirToPlayer = (playerPos - ballPos).Unit
    local dot = 0
    if speed > 0.1 then
        dot = dirToPlayer:Dot(vel.Unit)
    end
    if dot < 0 then LastBallHit = nil end

    -- Clash spam: ball on you and very close
    if targeted and dist <= SETTINGS.ClashDistance then
        if ring then ring.Color = Color3.fromRGB(255, 0, 0) end
        SendClick(true, ball)
        return
    end

    if targeted and dot > 0 then
        if ring then ring.Color = Color3.fromRGB(0, 255, 255) end
        local ping = GetPingSeconds()
        local threshold = SETTINGS.TimeThreshold
        if SETTINGS.PingBased then
            threshold = threshold + (ping * SETTINGS.PingOffset * 0.1)
        end
        if speed > 150 then
            threshold = threshold * 1.15
        end
        local timeToHit = dist / math.max(speed, 1)
        if timeToHit <= threshold or dist <= SETTINGS.EmergencyRadius then
            SendClick(false, ball)
        end
    else
        if ring then
            ring.Color = Color3.fromRGB(150, 240, 255)
            ring.Transparency = 0.6
        end
    end
end)

Player.CharacterAdded:Connect(function()
    LastBallHit = nil
    IsParrying = false
end)

print("[BladeAuto] Loaded. Press L to toggle.")
