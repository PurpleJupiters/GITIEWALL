"""
Phone App Installer — Agent WALL
Just tap Install on your phone. Next app opens automatically when done.
Press any key to skip an app.
"""
import subprocess, time, msvcrt

DEVICE = "AE6RUT4531003110"

APPS = [
    # Productivity
    ("ElevenLabs",          "io.elevenlabs.elevenlabs"),
    ("Notion",              "notion.id"),
    ("Microsoft Word",      "com.microsoft.office.word"),
    ("Replit",              "com.replit.app"),
    ("Kimi",                "com.moonshot.kimi"),
    # Music & Audio
    ("TIDAL",               "com.aspiro.tidal"),
    ("Bandcamp",            "com.bandcamp.android"),
    ("BandLab",             "com.bandlab.bandlab"),
    ("Bandsintown",         "com.bandsintown"),
    ("n-Track Studio",      "com.ntrack.studio"),
    ("Moises",              "com.moises.moises"),
    ("Perfect Ear",         "com.evilduck.musiciankit"),
    ("Sing Sharp",          "com.singsharp.app"),
    ("Vampr",               "com.vampr.vampr"),
    ("Sonos",               "com.sonos.acr"),
    ("Bose Connect",        "com.bose.boseconnect"),
    ("Chordify",            "com.chordify.chordify"),
    ("Nyx Music Player",    "com.awedea.nyx"),
    # Social
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
    # Streaming & News
    ("Prime Video",         "com.amazon.avod.thirdpartyclient"),
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
    # Other
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

def is_installed(pkg):
    r = subprocess.run(["adb", "-s", DEVICE, "shell", "pm", "list", "packages", pkg],
                       capture_output=True, text=True)
    return pkg in r.stdout

def open_store(pkg):
    subprocess.run(["adb", "-s", DEVICE, "shell", "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-d", f"market://details?id={pkg}"],
                   capture_output=True)

def flush_keys():
    while msvcrt.kbhit():
        msvcrt.getch()

total = len(APPS)
done  = 0
fresh = []

print("=" * 50)
print(f"  APP INSTALLER  —  {total} apps")
print(f"  Tap Install on phone. Auto-advances when done.")
print(f"  Any key = skip current app.")
print("=" * 50)

for i, (name, pkg) in enumerate(APPS, 1):
    if is_installed(pkg):
        print(f"[{i}/{total}] already installed — {name}")
        done += 1
        continue

    flush_keys()
    print(f"\n[{i}/{total}] {name}")
    print(f"  -> Opening Play Store on your phone...")
    open_store(pkg)
    print(f"  -> Tap INSTALL.  (any key = skip)")

    for _ in range(180):        # wait up to 3 min
        time.sleep(1)
        if is_installed(pkg):
            print(f"  ✅ Installed!")
            fresh.append(name)
            done += 1
            break
        if msvcrt.kbhit():
            flush_keys()
            print(f"  ⏭  Skipped.")
            break
    else:
        print(f"  ⏱  Timed out — skipping.")

print(f"\n{'=' * 50}")
print(f"  Done!  {len(fresh)} newly installed, {done} total.")
print("=" * 50)
input("Press ENTER to close.")
