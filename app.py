"""Shorts Studio - one app for: describing a video and getting an upload-ready Short or long YouTube
video (script, voice, footage, captions, thumbnail, optional private upload), tracking clients and
income toward a monthly goal, pitching creators, and staying inside YouTube's rules.

Run:  streamlit run app.py
"""
import datetime as dt
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import engine

BASE = Path(__file__).parent
DATA, OUT, CACHE = BASE / "data", BASE / "output", BASE / "cache"
for d in (DATA, OUT, CACHE):
    d.mkdir(exist_ok=True)

st.set_page_config(page_title="Shorts Studio", page_icon="🎬", layout="wide")


# ---------- database ----------
def db():
    con = sqlite3.connect(DATA / "studio.db")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS scripts(id INTEGER PRIMARY KEY, created TEXT, title TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT, platform TEXT,
        service TEXT, rate REAL, status TEXT, notes TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, date TEXT, client TEXT,
        amount REAL, note TEXT);
    CREATE TABLE IF NOT EXISTS outreach(date TEXT PRIMARY KEY, sent INTEGER, replies INTEGER);
    """)
    return con


# ---------- sidebar ----------
st.sidebar.title("🎬 Shorts Studio")
api_key = st.sidebar.text_input("Pexels API key (free)", value=os.getenv("PEXELS_API_KEY", ""), type="password",
                                help="Get one free at pexels.com/api")
anthropic_key = st.sidebar.text_input("Anthropic API key (for AI drafts)", value=os.getenv("ANTHROPIC_API_KEY", ""),
                                      type="password", help="console.anthropic.com. Optional: you can write scripts yourself.")
yt_file = st.sidebar.file_uploader("YouTube OAuth file (client_secret.json), optional", type=["json"])
if yt_file is not None:
    (DATA / "client_secret.json").write_bytes(yt_file.read())
    st.sidebar.success("Saved. First upload will ask you to log in to Google.")
voice_label = st.sidebar.selectbox("Voice / language", list(engine.VOICES))
speed = st.sidebar.slider("Voice speed (%)", -20, 30, 5)
font = st.sidebar.text_input("Caption font", "Arial",
                             help="For Telugu/Hindi/Tamil use a font that has those glyphs, e.g. 'Noto Sans Telugu'.")
goal = st.sidebar.number_input("Monthly goal (₹)", 1000, 500000, 20000, step=1000)
if not engine.ffmpeg_available():
    st.sidebar.error("ffmpeg not found. Install it (see README) and restart.")

tab_make, tab_money, tab_pitch, tab_rules = st.tabs(
    ["1. Describe & Create", "2. Clients & Income", "3. Pitch creators", "4. YouTube rules check"])

# ================= TAB 1: DESCRIBE & CREATE =================
with tab_make:
    ss = st.session_state
    for k in ("title_in", "script_in", "kw_in", "desc_in", "tags_in"):
        ss.setdefault(k, "")

    st.subheader("Describe the video, review the draft, get an upload-ready file")
    st.caption("Flow: 1) describe it  2) AI drafts  3) YOU review and edit  4) render  5) upload as a private draft.")

    a1, a2 = st.columns([3, 2])
    with a1:
        fmt = st.radio("Format", ["Short / Reel (vertical, ~45 sec)", "Long YouTube video (16:9)"], horizontal=True)
        kind = "short" if fmt.startswith("Short") else "long"
        minutes = st.slider("Length (minutes)", 2, 8, 4) if kind == "long" else 1
        niche = st.text_input("Your niche", "AI tools")
        idea = st.text_area("What video do you want? (one or two sentences)", height=80,
                            placeholder="e.g. 3 free AI tools that save a student time on assignments")
        if st.button("✨ Draft with AI"):
            if not anthropic_key:
                st.error("Add your Anthropic API key in the sidebar (or write the script yourself below).")
            elif not idea.strip():
                st.error("Describe the video first.")
            else:
                try:
                    with st.spinner("Drafting script, footage keywords and metadata..."):
                        d = engine.ai_draft(idea, niche, voice_label.split(" - ")[0], kind, minutes, anthropic_key)
                    ss["title_in"], ss["script_in"] = d["title"], d["script"]
                    ss["kw_in"] = "\n".join(d["keywords"])
                    ss["desc_in"] = d["description"]
                    ss["tags_in"] = ", ".join(d["tags"])
                    ss.pop("result", None)
                    st.success("Draft ready below. Read it, check every fact, and make it your own before rendering.")
                except Exception as e:
                    st.error(f"Draft failed: {e}")
    with a2:
        st.markdown("**Before you render**")
        ok_review = st.checkbox("I reviewed and edited this script. It is accurate and adds my own value "
                                "(experience, examples, opinion).")
        ok_media = st.checkbox("I'm only using footage/music I have the right to use.")
        synth = st.checkbox("Video contains REALISTIC synthetic content (e.g. cloned voice of a real person, "
                            "fake realistic events). Leave off for a plain narrator + stock footage.")
        st.caption("AI help is fine; mass-produced, unreviewed, repetitive content is what gets channels "
                   "demonetised. The tool blocks near-duplicate scripts.")

    ss["title_in"] = st.text_input("Title", ss["title_in"], max_chars=100)
    ss["script_in"] = st.text_area("Script (narration)", ss["script_in"], height=240)
    ss["kw_in"] = st.text_area("Footage keywords (one per line, English)", ss["kw_in"], height=120)
    ss["desc_in"] = st.text_area("Description", ss["desc_in"], height=100)
    ss["tags_in"] = st.text_input("Tags (comma separated)", ss["tags_in"])
    music = st.file_uploader("Optional background music (ONLY music you own or that is royalty-free)", type=["mp3"])

    if st.button("🎬 Render video", type="primary"):
        script, title = ss["script_in"], ss["title_in"].strip()
        con = db()
        prev = [r[0] for r in con.execute("SELECT text FROM scripts").fetchall()]
        today_n = con.execute("SELECT COUNT(*) FROM scripts WHERE created LIKE ?",
                              (dt.date.today().strftime("%Y%m%d") + "%",)).fetchone()[0]
        probs = engine.script_problems(script, kind)
        sim = engine.max_similarity(script, prev)
        if not engine.ffmpeg_available():
            st.error("Install ffmpeg first.")
        elif not api_key:
            st.error("Add your free Pexels API key in the sidebar.")
        elif not (ok_review and ok_media):
            st.error("Tick both confirmation boxes first.")
        elif not title:
            st.error("Add a title.")
        elif probs:
            for p in probs:
                st.error(p)
        elif sim > 0.8:
            st.error(f"This script is {sim:.0%} similar to one you already made. Make it genuinely different.")
        else:
            if today_n >= 3:
                st.warning(f"You've already made {today_n} videos today. YouTube rewards quality over volume.")
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                with st.status("Building your video...", expanded=True) as stat:
                    st.write("Recording voiceover...")
                    mp3 = OUT / f"{stamp}_voice.mp3"
                    words = engine.synthesize(script, engine.VOICES[voice_label], speed, mp3)
                    dur = engine.media_duration(mp3)
                    st.write(f"Voiceover ready ({dur:.0f}s). Fetching footage...")
                    orient = "portrait" if kind == "short" else "landscape"
                    used, clips = set(), []
                    for q in [k.strip() for k in ss["kw_in"].splitlines() if k.strip()][:40]:
                        c = engine.pexels_clip(q, api_key, CACHE, used, orientation=orient)
                        if c:
                            clips.append(c)
                        else:
                            st.write(f"No clip found for '{q}', skipping.")
                    if not clips:
                        raise RuntimeError("No footage found. Try different keywords.")
                    st.write("Adding captions and rendering (long videos take a few minutes)...")
                    srt = engine.build_srt(words, script, dur,
                                           words_per_caption=3 if kind == "short" else 6,
                                           upper=(kind == "short"))
                    srt_path = OUT / f"{kind}_{stamp}.srt"
                    srt_path.write_text(srt, encoding="utf-8")
                    mpath = None
                    if music:
                        mpath = OUT / f"{stamp}_music.mp3"
                        mpath.write_bytes(music.read())
                    final = engine.render_video(clips, mp3, srt, OUT / f"{kind}_{stamp}.mp4",
                                                kind=kind, font=font, music_path=mpath)
                    thumb = None
                    if kind == "long":
                        st.write("Making thumbnail...")
                        thumb = engine.make_thumbnail(final, title, OUT / f"{kind}_{stamp}_thumb.jpg")
                    con.execute("INSERT INTO scripts(created,title,text) VALUES(?,?,?)", (stamp, title, script))
                    con.commit()
                    stat.update(label="Done", state="complete")
                ss["result"] = {"video": str(final), "thumb": str(thumb) if thumb else None,
                                "srt": str(srt_path), "kind": kind}
            except Exception as e:  # show the real error
                st.error(f"Failed: {e}")

    res = ss.get("result")
    if res:
        st.success("Your video is ready.")
        vcol, tcol = st.columns([1, 1])
        with vcol:
            st.video(res["video"])
        with tcol:
            if res["thumb"]:
                st.image(res["thumb"], caption="Thumbnail (1280x720)")
            vb = Path(res["video"])
            st.download_button("⬇️ Download MP4", vb.read_bytes(), file_name=vb.name, mime="video/mp4")
            sb = Path(res["srt"])
            st.download_button("⬇️ Download captions (.srt)", sb.read_bytes(), file_name=sb.name)
            if res["thumb"]:
                tb = Path(res["thumb"])
                st.download_button("⬇️ Download thumbnail", tb.read_bytes(), file_name=tb.name, mime="image/jpeg")

        st.markdown("#### Upload to YouTube")
        u1, u2, u3 = st.columns(3)
        privacy = u1.selectbox("Visibility", ["private", "unlisted", "public"],
                               help="Private is safest: review in YouTube Studio, then publish yourself.")
        cat = u2.selectbox("Category", ["27", "28", "22"],
                           format_func=lambda k: {"27": "Education", "28": "Science & Technology",
                                                  "22": "People & Blogs"}[k])
        if privacy == "public":
            st.warning("Publishing straight away skips your last review. Private first is recommended.")
        secrets = DATA / "client_secret.json"
        if not secrets.exists():
            st.info("To upload from here, add your YouTube OAuth file in the sidebar (steps are in README). "
                    "Or just download the MP4 and upload it yourself in YouTube Studio.")
        if st.button("⬆️ Upload to my YouTube channel", disabled=not secrets.exists()):
            try:
                import uploader
                bar = st.progress(0.0)
                url, note = uploader.upload_video(
                    res["video"], ss["title_in"], ss["desc_in"],
                    [t.strip() for t in ss["tags_in"].split(",") if t.strip()],
                    secrets, DATA / "token.json", thumbnail_path=res["thumb"], privacy=privacy,
                    contains_synthetic_media=synth, category_id=cat, is_short=(res["kind"] == "short"),
                    progress_cb=lambda p: bar.progress(min(p, 1.0)))
                bar.progress(1.0)
                st.success(f"Uploaded as {privacy}. Open it in YouTube Studio: {url}{note}")
            except Exception as e:
                st.error(f"Upload failed: {e}")


# ================= TAB 2: MONEY =================
with tab_money:
    st.subheader("Clients & income")
    con = db()
    left, right = st.columns(2)
    with left:
        st.markdown("**Add / update a client**")
        with st.form("client", clear_on_submit=True):
            n = st.text_input("Client / creator name")
            plat = st.selectbox("Platform", ["Instagram", "YouTube", "LinkedIn", "Fiverr", "Upwork", "Internshala", "Other"])
            svc = st.text_input("Service", "12 reels / month")
            rate = st.number_input("Monthly value (₹)", 0, 500000, 6000, step=500)
            status = st.selectbox("Status", ["Lead", "Sample sent", "Trial", "Active retainer", "Lost"])
            notes = st.text_input("Notes")
            if st.form_submit_button("Save client") and n:
                con.execute("INSERT INTO clients(name,platform,service,rate,status,notes) VALUES(?,?,?,?,?,?)",
                            (n, plat, svc, rate, status, notes))
                con.commit()
                st.rerun()
    with right:
        st.markdown("**Log a payment received**")
        with st.form("pay", clear_on_submit=True):
            cl = st.text_input("From")
            amt = st.number_input("Amount (₹)", 0, 500000, 0, step=100)
            nt = st.text_input("Note", "")
            d = st.date_input("Date", dt.date.today())
            if st.form_submit_button("Log payment") and amt > 0:
                con.execute("INSERT INTO payments(date,client,amount,note) VALUES(?,?,?,?)",
                            (str(d), cl, amt, nt))
                con.commit()
                st.rerun()

    clients = pd.read_sql("SELECT * FROM clients", con)
    pays = pd.read_sql("SELECT * FROM payments", con)
    month = dt.date.today().strftime("%Y-%m")
    earned = pays[pays["date"].str.startswith(month)]["amount"].sum() if not pays.empty else 0
    active = clients[clients["status"] == "Active retainer"]["rate"].sum() if not clients.empty else 0
    pipeline = clients[clients["status"].isin(["Lead", "Sample sent", "Trial"])]["rate"].sum() if not clients.empty else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Earned this month", f"₹{earned:,.0f}", f"{earned / goal:.0%} of goal")
    m2.metric("Active retainers / month", f"₹{active:,.0f}")
    m3.metric("Pipeline (not yet paying)", f"₹{pipeline:,.0f}")
    st.progress(min(earned / goal, 1.0))
    gap = max(goal - active, 0)
    if gap:
        avg = (clients[clients["status"] == "Active retainer"]["rate"].mean() if not active == 0 else 6000)
        st.info(f"To reach ₹{goal:,.0f}/month from retainers you still need about ₹{gap:,.0f} more, "
                f"roughly {int(-(-gap // max(avg, 1)))} more client(s) at ₹{avg:,.0f}.")
    else:
        st.success("Your active retainers already cover your goal.")

    st.markdown("**Daily outreach** (consistency is what lands clients)")
    today = str(dt.date.today())
    row = con.execute("SELECT sent, replies FROM outreach WHERE date=?", (today,)).fetchone() or (0, 0)
    o1, o2 = st.columns(2)
    sent = o1.number_input("DMs/emails sent today", 0, 200, row[0])
    rep = o2.number_input("Replies today", 0, 200, row[1])
    if st.button("Save today's outreach"):
        con.execute("INSERT OR REPLACE INTO outreach(date,sent,replies) VALUES(?,?,?)", (today, sent, rep))
        con.commit()
        st.success("Saved")

    st.markdown("**Clients**")
    st.dataframe(clients, width="stretch", hide_index=True)
    st.markdown("**Payments**")
    st.dataframe(pays, width="stretch", hide_index=True)

# ================= TAB 3: PITCH =================
with tab_pitch:
    st.subheader("Pitch template generator")
    p1, p2 = st.columns(2)
    me = p1.text_input("Your name", "")
    creator = p1.text_input("Creator / business name", "")
    their_niche = p1.text_input("Their niche", "finance")
    sample_link = p2.text_input("Link to your best sample reel", "")
    price = p2.number_input("Your offer: price for 4 trial reels (₹)", 0, 100000, 1500, step=100)
    st.code(
        f"Hi {creator or '[name]'}, I watch your {their_niche} content. "
        f"I noticed your reels could hold viewers longer with tighter cuts and bold captions in the first 3 seconds.\n\n"
        f"I'm {me or '[your name]'}, a short-form editor. Here is a sample: {sample_link or '[link]'}.\n\n"
        f"I'd love to edit 4 trial reels for ₹{price:,}. If you like them, we can do a monthly plan. "
        f"Want me to send a quick sample from one of your own clips first?",
        language=None)
    st.caption("Personalise each message (mention a specific video of theirs). Send 10 to 15 a day. "
               "Never pay anyone to give you work, and ignore any 'task for money' offers.")

# ================= TAB 4: RULES =================
with tab_rules:
    st.subheader("Stay monetisable: pre-upload checklist")
    st.markdown("""
- **Original value in every video**: your own script, angle, example or opinion. Not a re-read of someone else's article.
- **No reused content**: only footage, images, and music you have rights to (Pexels/Pixabay footage, royalty-free music).
- **No mass-produced sameness**: vary hooks, topics and structure. YouTube targets repetitive, templated channels.
- **Disclose realistic AI-generated or altered content** in YouTube Studio when it applies.
- **No misleading titles or thumbnails**, no fake claims, no income promises.
- **Finance/health niches**: give general education only, no personalised advice, no guaranteed returns.
- **Monetisation**: check current YPP thresholds in YouTube Studio (they change). Also keep Instagram posts original for creator payouts.
- **Never buy views, subs, or use sub-for-sub.** It risks the channel.
- **Taxes**: record your freelance income; speak to a CA once it grows.
""")
    st.warning("No tool can guarantee views or earnings. This app removes busywork and keeps you compliant. "
               "Growth still comes from your topic choice, hooks and consistency.")
