import subprocess, time, sys

DEVICE = "AE6RUT4531003110"
WAIT   = 15   # seconds per app before auto-skip

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

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return ""

def is_installed(pkg):
    return pkg in run(["adb", "-s", DEVICE, "shell", "pm", "list", "packages", pkg])

def open_store(pkg):
    run(["adb", "-s", DEVICE, "shell", "am", "start",
         "-a", "android.intent.action.VIEW", "-d", f"market://details?id={pkg}"])

total = len(APPS)
fresh = []

print(f"APP INSTALLER — {total} apps — tap Install on phone", flush=True)
print(f"Auto-skips after {WAIT}s if not installed\n", flush=True)

for i, (name, pkg) in enumerate(APPS, 1):
    if is_installed(pkg):
        print(f"[{i}/{total}] HAVE IT: {name}", flush=True)
        continue

    print(f"[{i}/{total}] OPENING: {name}", flush=True)
    open_store(pkg)

    installed = False
    for t in range(WAIT):
        time.sleep(1)
        if t % 10 == 9:
            print(f"  ...{WAIT - t - 1}s left", flush=True)
        if is_installed(pkg):
            installed = True
            break

    if installed:
        print(f"  DONE: {name}\n", flush=True)
        fresh.append(name)
    else:
        print(f"  SKIP: {name}\n", flush=True)

print(f"\nFINISHED — {len(fresh)} installed: {fresh}", flush=True)
input("Enter to close")
