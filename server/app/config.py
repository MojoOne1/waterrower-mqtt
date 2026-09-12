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

# The way back in when the admin password is lost: set this to 1 alongside
# a new ARENA_ADMIN_PASSWORD and restart. It resets the password of an
# existing admin account instead of only creating a missing one. Anyone who
# can edit the compose file can already read the database, so this gives
# away nothing they did not have - but take it out again afterwards, or the
# password goes back to whatever is in the file on every restart.
ADMIN_RESET = os.environ.get("ARENA_ADMIN_RESET", "0") == "1"

# Behind Cloudflare Tunnel the connection to the browser is HTTPS even though
# the app itself is spoken to over plain HTTP, so the cookie must still be
# Secure. Set to 0 only when testing over http://localhost.
SECURE_COOKIES = os.environ.get("ARENA_SECURE_COOKIES", "1") != "0"
SESSION_DAYS = float(os.environ.get("ARENA_SESSION_DAYS", "30"))

# How long a device may stay silent before the arena calls it offline. The
# tracker pings every 20 s, so this tolerates one lost ping.
UPLINK_TIMEOUT_S = float(os.environ.get("ARENA_UPLINK_TIMEOUT", "50"))

# Off by default: whether a session is over is the rower's call, not the
# race's. Somebody who crossed the line is usually still rowing it out, and
# a time race ending on the clock says nothing about whether they are done.
# Each athlete closes their own session - from the arena or from their own
# tracker. Set to 1 to have the finish do it for everyone.
END_AT_FINISH = os.environ.get("ARENA_END_AT_FINISH", "0") == "1"

# Sign-in and invitation lockouts. These are only the starting values: an
# admin changes them in the arena, and what they save is kept in the
# database and wins from then on. A limit of 0 switches a policy off.
#
# Each policy is "that many failures, then locked out for that many
# minutes" - and the same span is how long a failure is remembered, so an
# abandoned attempt ages out on its own.
SECURITY_DEFAULTS = {
    # One address guessing at any account.
    "login_ip_limit": int(os.environ.get("ARENA_LOGIN_IP_LIMIT", "10")),
    "login_ip_minutes": int(os.environ.get("ARENA_LOGIN_IP_MINUTES", "15")),
    # One account being guessed at from anywhere. Looser on purpose: this
    # one can be used to lock somebody out, so it should take some doing.
    "login_name_limit": int(os.environ.get("ARENA_LOGIN_NAME_LIMIT", "30")),
    "login_name_minutes": int(os.environ.get("ARENA_LOGIN_NAME_MINUTES", "15")),
    # Wrong invitation codes from one address. Codes are 96 bits, so a
    # wrong one is either a typo or somebody fishing.
    "invite_ip_limit": int(os.environ.get("ARENA_INVITE_IP_LIMIT", "10")),
    "invite_ip_minutes": int(os.environ.get("ARENA_INVITE_IP_MINUTES", "60")),
    # Trackers offering a device token that is not one. Guessing a 256-bit
    # token is hopeless, so this is not about the guessing - it is about
    # somebody opening sockets at the server all day for free.
    "uplink_ip_limit": int(os.environ.get("ARENA_UPLINK_IP_LIMIT", "10")),
    "uplink_ip_minutes": int(os.environ.get("ARENA_UPLINK_IP_MINUTES", "15")),
}

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
