"""
Phone App Installer — Agent WALL
Tap Install on phone. Auto-advances when done. Any key = skip.
"""
import subprocess, time, msvcrt

DEVICE = "AE6RUT4531003110"

# Only confirmed package names — no guesses
APPS = [
    ("Notion",              "notion.id"),
    ("Microsoft Word",      "com.microsoft.office.word"),
    ("Replit",              "com.replit.app"),
    ("Signal",              "org.thoughtcrime.securesms"),
    ("Discord",             "com.discord"),
    ("LinkedIn",            "com.linkedin.android"),
    ("Reddit",              "com.reddit.frontpage"),
    ("Tumblr",              "com.tumblr"),
    ("Letterboxd",          "com.letterboxd.android"),
    ("Mastodon",            "org.joinmastodon.android"),
    ("Bandcamp",            "com.bandcamp.android"),
    ("BandLab",             "com.bandlab.bandlab"),
    ("TIDAL",               "com.aspiro.tidal"),
    ("Sonos",               "com.sonos.acr"),
    ("Bose Connect",        "com.bose.boseconnect"),
    ("Lightroom",           "com.adobe.lrmobile"),
    ("Adobe Express",       "com.adobe.spark.post"),
    ("Picsart",             "com.picsart.studio"),
    ("InShot",              "com.camerasidus.vcut"),
    ("Pexels",              "com.pexels.pexels"),
    ("Vimeo",               "com.vimeo.networking"),
    ("Prime Video",         "com.amazon.avod.thirdpartyclient"),
    ("NOS",                 "nl.nos.android"),
    ("NPO Start",           "nl.uitzendinggemist"),
    ("Ziggo GO",            "nl.ziggo.tv"),
    ("BBC News",            "bbc.mobile.news.ww"),
    ("Reuters",             "com.thomsonreuters.reuters"),
    ("ING Bankieren",       "com.ing.diba.m4b.android"),
    ("MijnKPN",             "nl.kpn.mijnkpn"),
    ("NS International",    "nl.ns.android"),
    ("Tikkie",              "com.abnamro.nl.tikkie"),
    ("Marktplaats",         "com.marktplaats.marktplaats"),
    ("Easypark NL",         "net.easypark.android"),
    ("Pathe",               "nl.pathe.mobile"),
    ("JansApp",             "nl.storegear.jansapp.prod"),
    ("PayPal",              "com.paypal.android.p2pmobile"),
    ("WeTransfer",          "com.wetransfer.app"),
    ("Fiverr",              "com.fiverr.fiverr"),
    ("Udemy",               "com.udemy.android"),
    ("Outdooractive",       "com.outdooractive.android"),
    ("Frameo",              "net.frameo.app"),
    ("iRobot",              "com.irobot.home"),
    ("ReadEra",             "org.readera"),
    ("RepostExchange",      "com.repostexchange.app"),
]

def is_installed(pkg):
    try:
        r = subprocess.run(["adb", "-s", DEVICE, "shell", "pm", "list", "packages", pkg],
                           capture_output=True, text=True, timeout=8)
        return pkg in r.stdout
    except Exception:
        return False

def open_store(pkg):
    try:
        subprocess.run(["adb", "-s", DEVICE, "shell", "am", "start",
                        "-a", "android.intent.action.VIEW",
                        "-d", f"market://details?id={pkg}"],
                       capture_output=True, timeout=8)
    except Exception:
        pass

def flush_keys():
    while msvcrt.kbhit():
        msvcrt.getch()

total = len(APPS)
fresh = []

print("=" * 50)
print(f"  APP INSTALLER  —  {total} apps")
print(f"  Tap Install on phone. Auto-advances when done.")
print(f"  Any key = skip current app.")
print("=" * 50)

for i, (name, pkg) in enumerate(APPS, 1):
    if is_installed(pkg):
        print(f"[{i}/{total}] already installed — {name}")
        continue

    flush_keys()
    print(f"\n[{i}/{total}] {name}  —  opening Play Store...")
    open_store(pkg)
    print(f"  Tap INSTALL on phone  |  any key = skip")

    installed = False
    for _ in range(45):        # 45 second max — then auto-skip
        time.sleep(1)
        if is_installed(pkg):
            installed = True
            break
        if msvcrt.kbhit():
            flush_keys()
            break

    if installed:
        print(f"  ✅ Installed — next!")
        fresh.append(name)
    else:
        print(f"  ⏭  Skipped — next!")

print(f"\n{'=' * 50}")
print(f"  Done!  {len(fresh)} newly installed.")
if fresh:
    for a in fresh:
        print(f"    + {a}")
print("=" * 50)
input("Press ENTER to close.")
