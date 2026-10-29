# Shorts Studio

Describe a video in one sentence. The app drafts it, you review it, and it produces an upload-ready
Short (vertical) or long YouTube video (16:9): voiceover, stock footage, captions, thumbnail, title,
description and tags. It can upload to your channel as a private draft. It also tracks clients and income
toward your monthly goal and has a pitch generator and a YouTube policy checklist.

## Setup (one time)
1. Install Python 3.10+ and **ffmpeg** (Windows: `winget install ffmpeg`; Mac: `brew install ffmpeg`; Ubuntu: `sudo apt install ffmpeg`).
2. Free Pexels API key (stock footage): https://www.pexels.com/api/
3. Anthropic API key (AI drafts, optional, small cost per draft): https://console.anthropic.com
4. In this folder:
   ```
   pip install -r requirements.txt
   set PEXELS_API_KEY=your_key            (Windows)  |  export PEXELS_API_KEY=your_key            (Mac/Linux)
   set ANTHROPIC_API_KEY=your_key         (Windows)  |  export ANTHROPIC_API_KEY=your_key         (Mac/Linux)
   streamlit run app.py
   ```
   You can also paste the keys into the sidebar instead of setting variables.

## Daily workflow
1. Tab 1: pick Short or Long, write one sentence about the video, click **Draft with AI**.
2. **Read and edit** the script. Check every fact. Add your own example or opinion. Tick the confirmation boxes.
3. Click **Render video**. Download the MP4 (and thumbnail/captions), or click **Upload** to send it to YouTube as a private draft.
4. Open it in YouTube Studio, check it, then publish.
5. Log clients, payments and DMs in the Clients & Income tab.

## Optional: upload directly to YouTube (one time, about 10 minutes)
1. console.cloud.google.com -> new project -> enable **YouTube Data API v3**.
2. APIs & Services -> OAuth consent screen -> External -> add your own Google account as a Test user.
3. Credentials -> Create credentials -> OAuth client ID -> **Desktop app** -> download the JSON.
4. Upload that JSON in the app sidebar. The first upload opens a browser to ask your permission.
- Uploads default to **private** so you review before publishing.
- Custom thumbnails only work if your channel is verified (phone verification in YouTube Studio).
- The default API quota allows about 100 uploads a day, far more than you should post.

## Built-in safeguards
- AI drafts are allowed, but you must confirm you reviewed and edited the script.
- Script length gates: Short 40-170 words, long video 250-1500 words.
- Blocks scripts over 80% similar to one you already made. Warns after 3 videos in a day.
- Confirms you have rights to all footage and music.
- A checkbox sets YouTube's "altered or synthetic content" flag for realistic synthetic content
  (leave off for a plain narrator over stock footage).
- No bulk or automatic posting. Every upload is a click you make.

## Notes
- Telugu/Hindi/Tamil captions need a font with those glyphs (e.g. "Noto Sans Telugu"). Set it in the sidebar.
  The thumbnail title uses a Latin bold font, so for non-English titles pass a font path in `make_thumbnail`.
- Stock footage is generic, so the strongest videos have your own angle in the script.
- No software can guarantee views or income. Consistency, topic choice and good hooks do that.
