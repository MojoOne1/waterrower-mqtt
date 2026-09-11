"""Environment configuration. Everything has a working default except the
admin password, which has to be set once to bootstrap the first login."""

import os

APP_VERSION = os.environ.get("APP_VERSION", "dev")
GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")

DB_PATH = os.environ.get("DB_PATH", "/data/arena.db")

# The first athlete, created on an empty database. Without a password the
# server still starts - it just says so in the log and stays locked.
ADMIN_USER = os.environ.get("ARENA_ADMIN_USER", "admin").strip().lower()
ADMIN_NAME = os.environ.get("ARENA_ADMIN_NAME", "Admin").strip()
ADMIN_PASSWORD = os.environ.get("ARENA_ADMIN_PASSWORD", "")

# Behind Cloudflare Tunnel the connection to the browser is HTTPS even though
# the app itself is spoken to over plain HTTP, so the cookie must still be
# Secure. Set to 0 only when testing over http://localhost.
SECURE_COOKIES = os.environ.get("ARENA_SECURE_COOKIES", "1") != "0"
SESSION_DAYS = float(os.environ.get("ARENA_SESSION_DAYS", "30"))

# How long a device may stay silent before the arena calls it offline. The
# tracker pings every 20 s, so this tolerates one lost ping.
UPLINK_TIMEOUT_S = float(os.environ.get("ARENA_UPLINK_TIMEOUT", "50"))

# Race pacing.
COUNTDOWN_S = int(os.environ.get("ARENA_COUNTDOWN", "10"))
TICK_HZ = float(os.environ.get("ARENA_TICK_HZ", "2"))
# After the winner finishes, stragglers get this long before the race is
# called; a 2 km race should not hang on someone who walked away.
FINISH_GRACE_S = float(os.environ.get("ARENA_FINISH_GRACE", "600"))

# Lane colours, handed out in order as athletes are created. Same categorical
# set the tracker's charts use.
LANE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8b5cf6", "#e0457b"]

# The standard efforts the leaderboards are computed for.
RECORD_DISTANCES = [500, 1000, 2000, 5000, 10000]
RECORD_TIMES = [300, 600, 1200, 1800, 3600]
