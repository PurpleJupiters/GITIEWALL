"""
Phone App Auto-Installer — Agent WALL
Opens Play Store for each missing app one by one.
Auto-advances when you tap Install and it finishes downloading.
Press ENTER at any time to skip an app.
"""
import subprocess, time, sys, threading

DEVICE = "AE6RUT4531003110"

APPS = [
    # AI & Productivity
    ("Claude",              "com.anthropic.claude"),
    ("Perplexity",          "ai.perplexity.app.android"),
    ("ElevenLabs",          "io.elevenlabs.app"),
    ("Notion",              "notion.id"),
    ("OneDrive",            "com.microsoft.skydrive"),
    ("M365 Copilot",        "com.microsoft.copilot"),
    ("Microsoft Word",      "com.microsoft.office.word"),
    ("Replit",              "com.replit.app"),
    ("Kimi",                "com.moonshot.kimi"),

    # Music & Audio
    ("TIDAL",               "com.aspiro.tidal"),
    ("Bandcamp",            "com.bandcamp.android"),
    ("BandLab",             "com.bandlab.bandlab"),
    ("Bandsintown",         "com.bandsintown"),
    ("n-Track Studio",      "com.ntrack.studio"),
    ("Moises",              "com.moises.app"),
    ("Perfect Ear",         "com.evilduck.musiciankit"),
    ("Sing Sharp",          "com.singsharp.app"),
    ("Vampr",               "com.vampr.vampr"),
    ("Sonos",               "com.sonos.acr"),
    ("Bose Connect",        "com.bose.boseconnect"),
    ("NetEase Music",       "com.netease.cloudmusic"),
    ("Nyx Music Player",    "com.awedea.nyx"),
    ("Chordify",            "com.chordify.chordify"),

    # Social & Communication
    ("Signal",              "org.thoughtcrime.securesms"),
    ("Discord",             "com.discord"),
    ("LinkedIn",            "com.linkedin.android"),
    ("Reddit",              "com.reddit.frontpage"),
    ("Mastodon",            "org.joinmastodon.android"),
    ("Letterboxd",          "com.letterboxd.android"),
    ("Tumblr",              "com.tumblr"),
    ("ResearchGate",        "com.researchgate.net"),

    # Photo & Video
    ("Lightroom",           "com.adobe.lrmobile"),
    ("Adobe Express",       "com.adobe.spark.post"),
    ("Picsart",             "com.picsart.studio"),
    ("InShot",              "com.camerasidus.vcut"),
    ("Edits (Meta)",        "com.instagram.edits"),
    ("Pexels",              "com.pexels.pexels"),
    ("Vimeo",               "com.vimeo.networking"),
    ("Photo & Picture Resizer", "com.photo.resize.compress"),

    # Streaming & News
    ("Prime Video",         "com.amazon.avod.thirdpartyclient"),
    ("DStv Stream",         "com.dstv.stream"),
    ("NOS",                 "nl.nos.android"),
    ("NPO Start",           "nl.uitzendinggemist"),
    ("Ziggo GO",            "nl.ziggo.tv"),
    ("BBC News",            "bbc.mobile.news.ww"),
    ("Reuters",             "com.thomsonreuters.reuters"),

    # Dutch Apps
    ("ING Bankieren",       "com.ing.diba.m4b.android"),
    ("DigiD",               "nl.rijksoverheid.rdw.digid"),
    ("MijnKPN",             "nl.kpn.mijnkpn"),
    ("NS International",    "nl.ns.android"),
    ("Tikkie",              "com.abnamro.nl.tikkie"),
    ("Thuisbezorgd",        "com.thuisbezorgd.consumerapp"),
    ("Marktplaats",         "com.marktplaats.marktplaats"),
    ("Easypark NL",         "net.easypark.android"),
    ("Pathe",               "nl.pathe.mobile"),
    ("JansApp",             "nl.storegear.jansapp.prod"),

    # Utilities & Other
    ("PayPal",              "com.paypal.android.p2pmobile"),
    ("WeTransfer",          "com.wetransfer.app"),
    ("Fiverr",              "com.fiverr.fiverr"),
    ("Udemy",               "com.udemy.android"),
    ("Outdooractive",       "com.outdooractive.android"),
    ("Localcast",           "com.localcast.app"),
    ("Frameo",              "net.frameo.app"),
    ("iRobot",              "com.irobot.home"),
    ("CleanEmail",          "com.cleanemailapp.android"),
    ("ReadEra",             "org.readera"),
    ("RepostExchange",      "com.repostexchange.app"),
    ("Skool",               "com.skool.android"),
]

def is_installed(package):
    r = subprocess.run(
        ["adb", "-s", DEVICE, "shell", "pm", "list", "packages", package],
        capture_output=True, text=True
    )
    return package in r.stdout

def open_playstore(package):
    subprocess.run([
        "adb", "-s", DEVICE, "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", f"market://details?id={package}"
    ], capture_output=True)

# Skip flag set by Enter key thread
skip_flag = threading.Event()

def listen_for_skip():
    while True:
        input()
        skip_flag.set()

skip_thread = threading.Thread(target=listen_for_skip, daemon=True)
skip_thread.start()

total   = len(APPS)
already = 0
fresh   = []
skipped = []

print("=" * 55)
print(f"  PHONE APP INSTALLER — {total} apps queued")
print("  Press ENTER anytime to skip to the next app")
print("=" * 55)

for i, (name, package) in enumerate(APPS, 1):
    if is_installed(package):
        print(f"[{i:02d}/{total}] ✓ Already installed: {name}")
        already += 1
        continue

    skip_flag.clear()
    print(f"\n[{i:02d}/{total}] ▶  Opening Play Store → {name}")
    open_playstore(package)
    print(f"          Tap INSTALL on your phone.")
    print(f"          (Auto-advances when done | ENTER = skip)")

    timeout = 120   # 2 min max per app — press ENTER to skip anytime
    elapsed = 0
    result  = "timeout"

    while elapsed < timeout:
        time.sleep(3)
        elapsed += 3
        if is_installed(package):
            result = "installed"
            break
        if skip_flag.is_set():
            result = "skipped"
            break

    if result == "installed":
        print(f"          ✅ Installed! Next up...")
        fresh.append(name)
    elif result == "skipped":
        print(f"          ⏭  Skipped: {name}")
        skipped.append(name)
    else:
        print(f"          ⏱  Timed out — moving on: {name}")
        skipped.append(name)

    time.sleep(1)

print("\n" + "=" * 55)
print(f"  DONE")
print(f"  Already installed : {already}")
print(f"  Newly installed   : {len(fresh)}")
print(f"  Skipped / timeout : {len(skipped)}")
if skipped:
    print(f"\n  Not installed:")
    for s in skipped:
        print(f"    - {s}")
print("=" * 55)
input("\nPress ENTER to close.")
